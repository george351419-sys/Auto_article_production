"""Five-dimension topic scoring engine.

Implements the core scoring algorithm from PRD V1.0:
  1. Dimension-level scoring (0-100 each, using rules + optional LLM)
  2. Weighted total based on mode (new/old account) × platform (wechat/toutiao/xiaohongshu)
  3. Bonus/penalty adjustments
  4. Grade assignment (S/A/B/C)

Supports two positioning modes:
  - business_tech: 商业/科技 (original)
  - entertainment: 娱乐/鸡汤 (new)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from core.models import DimensionScores, ScoreResult

logger = logging.getLogger("scoring_engine")

# ── Positioning ─────────────────────────────────────────────────────────

POSITIONING = {
    "business_tech": "商业科技",
    "entertainment": "娱乐鸡汤",
}

# ── Weight templates (from PRD 3.2.2) ───────────────────────────────────

WEIGHTS = {
    "new_account": {
        "wechat": {"relevance": 0.40, "timeliness": 0.25, "value": 0.15, "compliance": 0.12, "competition": 0.08},
        "toutiao": {"relevance": 0.35, "timeliness": 0.35, "value": 0.10, "compliance": 0.15, "competition": 0.15},
        "xiaohongshu": {"relevance": 0.35, "timeliness": 0.25, "value": 0.20, "compliance": 0.12, "competition": 0.08},
    },
    "old_account": {
        "wechat": {"relevance": 0.35, "timeliness": 0.20, "value": 0.25, "compliance": 0.12, "competition": 0.08},
        "toutiao": {"relevance": 0.30, "timeliness": 0.30, "value": 0.15, "compliance": 0.15, "competition": 0.10},
        "xiaohongshu": {"relevance": 0.32, "timeliness": 0.20, "value": 0.28, "compliance": 0.12, "competition": 0.08},
    },
}

# Entertainment/鸡汤 weights — higher timeliness/value, lower relevance
WEIGHTS_ENTERTAINMENT = {
    "new_account": {
        "wechat": {"relevance": 0.30, "timeliness": 0.35, "value": 0.20, "compliance": 0.10, "competition": 0.05},
        "toutiao": {"relevance": 0.28, "timeliness": 0.38, "value": 0.18, "compliance": 0.11, "competition": 0.05},
        "xiaohongshu": {"relevance": 0.30, "timeliness": 0.32, "value": 0.25, "compliance": 0.08, "competition": 0.05},
    },
    "old_account": {
        "wechat": {"relevance": 0.25, "timeliness": 0.25, "value": 0.30, "compliance": 0.12, "competition": 0.08},
        "toutiao": {"relevance": 0.23, "timeliness": 0.30, "value": 0.25, "compliance": 0.14, "competition": 0.08},
        "xiaohongshu": {"relevance": 0.25, "timeliness": 0.22, "value": 0.33, "compliance": 0.12, "competition": 0.08},
    },
}

GRADE_THRESHOLDS = {"S": 90, "A": 80, "B": 70, "C": 0}

PLATFORM_LABELS = {
    "wechat": "公众号",
    "toutiao": "今日头条",
    "xiaohongshu": "小红书",
}


# ── Dimension scoring rules ─────────────────────────────────────────────
# Each dimension uses keyword-based heuristics to estimate 0-100 score.
# These are deterministic baselines; LLM can override if enabled.

def _score_relevance(title: str, content: str) -> float:
    """领域相关性: how well the topic fits tech/business vertical."""
    core_keywords = [
        "AI", "人工智能", "大模型", "GPT", "Claude", "大厂", "互联网", "腾讯", "阿里", "字节",
        "谷歌", "微软", "苹果", "英伟达", "芯片", "创投", "融资", "IPO", "上市",
        "新能源", "电动车", "特斯拉", "比亚迪", "自动驾驶", "机器人",
        "行业新规", "监管", "数字经济", "数据", "云计算", "SaaS",
        "商业模式", "增长",
    ]
    secondary_keywords = [
        "手机", "硬件", "软件", "应用", "开发", "程序员", "创业", "职场",
        "消费", "品牌", "营销", "零售", "电商", "出海", "供应链",
        "金融", "投资", "股票", "基金", "区块链", "Web3", "产品",
    ]
    # Negative keywords — presence of these strongly indicates NOT tech/business
    negative_keywords = [
        "吃瓜", "离婚", "出轨", "绯闻", "八卦", "综艺", "选秀",
        "娱乐圈", "明星", "偶像", "粉丝", "应援", "恋爱",
    ]
    text = f"{title} {content}".lower()
    core_hits = sum(1 for kw in core_keywords if kw.lower() in text)
    secondary_hits = sum(1 for kw in secondary_keywords if kw.lower() in text)
    neg_hits = sum(1 for kw in negative_keywords if kw.lower() in text)

    # Strong penalty for entertainment/gossip keywords
    if neg_hits >= 3: return 20.0
    if neg_hits >= 2: return 30.0
    if neg_hits >= 1: return 45.0

    if core_hits >= 5: return 95.0
    if core_hits >= 3: return 88.0
    if core_hits >= 2: return 82.0
    if core_hits >= 1: return 75.0
    if secondary_hits >= 3: return 65.0
    if secondary_hits >= 1: return 50.0
    return 30.0


def _score_timeliness(title: str, content: str) -> float:
    """热点时效性: recency and trending status."""
    text = f"{title} {content}".lower()
    hours_patterns = [
        (r"刚刚|突发|最新|快讯|刚刚发布", 95.0),
        (r"今天|今日|今晚|今晨|今天早上|今天下午", 92.0),
        (r"昨天|昨日|昨", 85.0),
        (r"本周|近日|最近|近几日", 78.0),
        (r"上周|上月|月初|月底", 60.0),
        (r"今年|[0-9]+月[0-9]+日", 55.0),
    ]
    for pattern, score in hours_patterns:
        if re.search(pattern, text):
            return score
    # Default: check for hot/top indicators
    hot_indicators = ["热搜", "热榜", "TOP", "刷屏", "爆款", "刷爆", "热议", "关注"]
    if any(w in text for w in hot_indicators):
        return 82.0
    return 50.0


def _score_value(title: str, content: str) -> float:
    """内容价值延展性: can it be interpreted across multiple dimensions?"""
    text = f"{title} {content}".lower()
    deep_indicators = [
        "趋势", "预判", "复盘", "启发", "避坑", "普通人", "落地", "实操",
        "方法论", "底层逻辑", "案例", "数据", "分析", "解读", "观点",
        "框架", "模型", "策略", "建议", "指南", "干货",
    ]
    shallow_indicators = ["流水账", "资讯", "快讯", "简讯", "摘要"]

    deep_hits = sum(1 for w in deep_indicators if w in text)
    shallow_hits = sum(1 for w in shallow_indicators if w in text)

    if deep_hits >= 4: return 93.0
    if deep_hits >= 2: return 85.0
    if deep_hits >= 1: return 78.0
    if shallow_hits >= 2: return 45.0
    if shallow_hits >= 1: return 55.0
    # By length: longer content implies more room for value
    if len(content) > 500: return 72.0
    if len(content) > 200: return 65.0
    return 55.0


def _score_compliance(title: str, content: str) -> float:
    """合规风险度 (反向): higher score = lower risk."""
    text = f"{title} {content}".lower()
    high_risk = [
        "敏感", "政治", "时政", "违规", "封禁", "造谣", "谣言",
        "色情", "暴力", "攻击", "诋毁", "抹黑", "虚假", "诈骗",
        "虚拟币", "炒币", "荐股", "理财建议", "非法",
    ]
    medium_risk = ["争议", "质疑", "指责", "批评", "负面", "丑闻", "投诉"]
    low_risk_indicators = ["官方公告", "白皮书", "财报", "数据来源", "权威", "公开数据"]

    high_hits = sum(1 for w in high_risk if w in text)
    medium_hits = sum(1 for w in medium_risk if w in text)
    low_hits = sum(1 for w in low_risk_indicators if w in text)

    if high_hits >= 2: return 15.0
    if high_hits >= 1: return 35.0
    if medium_hits >= 2: return 55.0
    if medium_hits >= 1: return 70.0
    if low_hits >= 2: return 95.0
    if low_hits >= 1: return 88.0
    return 85.0  # Default: medium-low risk


def _score_competition(title: str, content: str) -> float:
    """赛道竞争度 (反向): higher score = less competition (blue ocean)."""
    text = f"{title} {content}".lower()
    red_ocean = ["热议", "刷屏", "热搜", "大家都在说", "刷爆", "疯传", "刷屏了"]
    niche = ["蓝海", "独家", "首发", "垂直", "细分", "非共识", "小众但重要", "被忽视"]

    red_hits = sum(1 for w in red_ocean if w in text)
    niche_hits = sum(1 for w in niche if w in text)

    if niche_hits >= 2: return 92.0
    if niche_hits >= 1: return 85.0
    if red_hits >= 2: return 40.0
    if red_hits >= 1: return 55.0
    # Default moderate competition
    return 68.0


SCORERS = {
    "relevance": _score_relevance,
    "timeliness": _score_timeliness,
    "value": _score_value,
    "compliance": _score_compliance,
    "competition": _score_competition,
}


# ── Entertainment/鸡汤 dimension scoring rules ──────────────────────────

def _score_relevance_entertainment(title: str, content: str) -> float:
    """领域相关性(娱乐/鸡汤): how well the topic fits entertainment/lifestyle vertical."""
    core_keywords = [
        "明星", "综艺", "影视", "音乐", "情感", "婚姻", "育儿", "成长",
        "励志", "治愈", "人生道理", "职场情商", "人际关系", "心理健康",
        "家庭教育", "生活美学", "旅行", "美食", "穿搭", "娱乐", "电影",
        "电视剧", "综艺节目", "真人秀", "脱口秀", "演唱会", "新歌",
        "恋爱", "分手", "复合", "婆媳", "亲子", "闺蜜", "兄弟",
    ]
    secondary_keywords = [
        "八卦", "CP", "粉丝", "追星", "剧集", "角色", "人物", "故事",
        "经历", "感悟", "态度", "观点", "生活方式", "日常", "打卡",
        "分享", "推荐", "测评", "开箱", "vlog", "好物", "种草",
        "拍照", "修图", "滤镜", "美妆", "护肤", "健身", "减脂",
    ]
    negative_keywords = [
        "政治", "时政", "敏感", "暴力", "色情", "违法", "违规",
        "军事", "外交", "恐怖", "毒品", "赌博",
    ]
    text = f"{title} {content}".lower()
    core_hits = sum(1 for kw in core_keywords if kw.lower() in text)
    secondary_hits = sum(1 for kw in secondary_keywords if kw.lower() in text)
    neg_hits = sum(1 for kw in negative_keywords if kw.lower() in text)

    if neg_hits >= 3: return 20.0
    if neg_hits >= 2: return 30.0
    if neg_hits >= 1: return 45.0

    if core_hits >= 5: return 95.0
    if core_hits >= 3: return 88.0
    if core_hits >= 2: return 82.0
    if core_hits >= 1: return 75.0
    if secondary_hits >= 3: return 65.0
    if secondary_hits >= 1: return 50.0
    return 30.0


def _score_timeliness_entertainment(title: str, content: str) -> float:
    """热点时效性(娱乐/鸡汤): recency and trending status for entertainment."""
    text = f"{title} {content}".lower()
    hours_patterns = [
        (r"刚刚|突发|正在|紧急|快讯|刚刚发布", 95.0),
        (r"今天|今日|今晚|今晨|今天早上|今天下午|热播|首播|上线|开播|更新", 92.0),
        (r"昨天|昨日|昨|昨晚", 85.0),
        (r"本周|近日|最近|近几日|本期|本季|这周|这期", 78.0),
        (r"上周|上月|月初|月底|月初", 60.0),
        (r"今年|[0-9]+月[0-9]+日|去年", 55.0),
    ]
    for pattern, score in hours_patterns:
        if re.search(pattern, text):
            return score
    hot_indicators = ["热搜", "霸榜", "刷屏", "爆了", "话题", "讨论", "热议", "关注", "热门"]
    if any(w in text for w in hot_indicators):
        return 82.0
    return 50.0


def _score_value_entertainment(title: str, content: str) -> float:
    """内容价值延展性(娱乐/鸡汤): emotional resonance and viral potential."""
    text = f"{title} {content}".lower()
    deep_indicators = [
        "情感共鸣", "观点独特", "故事感人", "引人思考", "干货", "实用",
        "方法", "技巧", "改变", "可模仿", "有争议", "深度", "治愈",
        "启发", "反思", "感悟", "道理", "智慧", "经验", "教训",
        "真实经历", "亲历", "自述", "访谈", "独家",
    ]
    shallow_indicators = ["纯资讯", "流水账", "搬运", "广告", "软文", "水文", "转载"]

    deep_hits = sum(1 for w in deep_indicators if w in text)
    shallow_hits = sum(1 for w in shallow_indicators if w in text)

    if deep_hits >= 4: return 93.0
    if deep_hits >= 2: return 85.0
    if deep_hits >= 1: return 78.0
    if shallow_hits >= 2: return 45.0
    if shallow_hits >= 1: return 55.0
    if len(content) > 500: return 72.0
    if len(content) > 200: return 65.0
    return 55.0


def _score_compliance_entertainment(title: str, content: str) -> float:
    """合规风险度(娱乐/鸡汤): higher score = lower risk for entertainment."""
    text = f"{title} {content}".lower()
    high_risk = [
        "隐私泄露", "偷拍", "造谣", "诽谤", "侵权", "抄袭", "洗稿",
        "虚假人设", "人肉", "色情", "低俗", "暴力", "违法",
    ]
    medium_risk = ["负面", "争议", "批评", "黑料", "爆料", "八卦过度", "撕逼", "引战"]
    low_risk_indicators = ["正能量", "官媒发布", "当事人授权", "原创声明", "真实经历", "公益"]

    high_hits = sum(1 for w in high_risk if w in text)
    medium_hits = sum(1 for w in medium_risk if w in text)
    low_hits = sum(1 for w in low_risk_indicators if w in text)

    if high_hits >= 2: return 15.0
    if high_hits >= 1: return 35.0
    if medium_hits >= 2: return 55.0
    if medium_hits >= 1: return 70.0
    if low_hits >= 2: return 95.0
    if low_hits >= 1: return 88.0
    return 85.0


def _score_competition_entertainment(title: str, content: str) -> float:
    """赛道竞争度(娱乐/鸡汤): higher score = less competition / unique angle."""
    text = f"{title} {content}".lower()
    red_ocean = ["大众热议", "全网刷屏", "大家都在看", "千篇一律", "刷屏了", "烂大街", "全都一样"]
    niche = ["独家角度", "另类解读", "冷门佳片", "小众", "独特观点", "冷门", "不为人知", "独特"]

    red_hits = sum(1 for w in red_ocean if w in text)
    niche_hits = sum(1 for w in niche if w in text)

    if niche_hits >= 2: return 92.0
    if niche_hits >= 1: return 85.0
    if red_hits >= 2: return 40.0
    if red_hits >= 1: return 55.0
    return 68.0


SCORERS_ENTERTAINMENT = {
    "relevance": _score_relevance_entertainment,
    "timeliness": _score_timeliness_entertainment,
    "value": _score_value_entertainment,
    "compliance": _score_compliance_entertainment,
    "competition": _score_competition_entertainment,
}


# ── Bonus / Penalty ─────────────────────────────────────────────────────

def _apply_bonus_penalty(title: str, content: str, weight_mode: str) -> tuple[float, list[dict]]:
    """Apply +/- adjustments. Returns (total_delta, [details])."""
    text = f"{title} {content}".lower()
    details = []

    # Bonus items
    bonuses = [
        (r"ai|人工智能|大模型|gpt|llm|aigc|智能体|机器人", 5.0, "AI新技术/大模型话题"),
        (r"财报|战略|收购|合并|ipo|上市|融资", 5.0, "大厂财报/战略/创投风口"),
        (r"新规|政策|法规|监管|国家|国务院|工信部", 5.0, "国家级数字经济新规"),
        (r"新能源|光伏|锂电|储能|碳中和|电动车", 5.0, "新能源突破话题"),
        (r"启发|思维|底层|认知|方法论|普通人|职场|搞钱|避坑", 4.0, "可输出普通人商业启发"),
        (r"官方|公告|白皮书|独家数据|权威媒体|信源", 3.0, "权威信源加分"),
        (r"热搜|标签|流量|关键词|搜索", 3.0, "高搜索关键词/高转发属性"),
    ]
    if weight_mode == "new_account":
        bonuses.append((r"入门|基础|1小时|轻松|简单|新手|快速", 4.0, "新号适配：低创作门槛"))

    for pattern, pts, reason in bonuses:
        if re.search(pattern, text):
            details.append({"type": "bonus", "name": reason, "points": pts})

    bonus_total = min(sum(d["points"] for d in details), 10.0)

    # Penalty items
    penalty_details = []
    penalties = [
        (r"^[^。]*$|纯资讯|转发|分享", -10.0, "仅可新闻复述，无解读空间"),
        (r"过期|上周|上月|上个月|去年", -8.0, "热点过期3天以上"),
        (r"股票|理财|虚拟币|炒币|荐股|投资建议", -10.0, "敏感金融/投资误导"),
        (r"小众|冷门|无人关注|不知名", -5.0, "小众冷门，无大众阅读需求"),
    ]
    if weight_mode == "new_account":
        penalties.append((r"数据复盘|高阶|专业壁垒|深度分析|复杂模型", -8.0, "新号不适配：专业壁垒极高"))

    for pattern, pts, reason in penalties:
        if re.search(pattern, text):
            penalty_details.append({"type": "penalty", "name": reason, "points": pts})

    penalty_total = sum(d["points"] for d in penalty_details)
    all_details = details + penalty_details

    return bonus_total + penalty_total, all_details


def _apply_bonus_penalty_entertainment(title: str, content: str, weight_mode: str) -> tuple[float, list[dict]]:
    """Apply +/- adjustments for entertainment/鸡汤 positioning."""
    text = f"{title} {content}".lower()
    details = []

    bonuses = [
        (r"独家|首发|一手|率先|抢先", 5.0, "独家爆料/一手信源"),
        (r"感动|泪目|破防|共鸣|触动|暖心", 5.0, "强烈情感共鸣"),
        (r"正能量|励志|逆袭|蜕变|成长|改变", 4.0, "正能量励志故事"),
        (r"技巧|方法|教程|指南|攻略|秘诀", 3.0, "实用生活技巧/方法"),
        (r"评论过万|转发过千|点赞|热门|刷屏|出圈", 3.0, "高互动传播属性"),
        (r"明星|偶像|网红|博主|大V|名人", 5.0, "名人/KOL相关话题"),
        (r"治愈|温暖|温馨|美好|幸福|日常", 4.0, "治愈系/温暖内容"),
    ]
    if weight_mode == "new_account":
        bonuses.append((r"简单|轻松|日常|随手|新手|入门", 4.0, "新号适配：低创作门槛"))

    for pattern, pts, reason in bonuses:
        if re.search(pattern, text):
            details.append({"type": "bonus", "name": reason, "points": pts})

    bonus_total = min(sum(d["points"] for d in details), 10.0)

    penalty_details = []
    penalties = [
        (r"纯搬运|复制粘贴|未经授权转载", -10.0, "纯搬运/无原创价值"),
        (r"过期|上周|上月|上个月|去年|旧闻", -8.0, "过期旧闻重发"),
        (r"负面|争议|撕逼|引战|互怼", -8.0, "负面争议内容"),
        (r"低俗|擦边|大尺度|露骨|挑逗", -10.0, "低俗擦边内容"),
        (r"千篇一律|烂大街|老生常谈|毫无新意", -5.0, "同质化无聊内容"),
    ]
    if weight_mode == "new_account":
        penalties.append((r"专业设备|专业摄影|专业后期|团队制作|复杂剪辑", -8.0, "新号不适配：制作门槛高"))

    for pattern, pts, reason in penalties:
        if re.search(pattern, text):
            penalty_details.append({"type": "penalty", "name": reason, "points": pts})

    penalty_total = sum(d["points"] for d in penalty_details)
    all_details = details + penalty_details

    return bonus_total + penalty_total, all_details


# ── Grade ────────────────────────────────────────────────────────────────

def _grade(total: float) -> str:
    if total >= 90: return "S"
    if total >= 80: return "A"
    if total >= 70: return "B"
    return "C"


# ── Main scoring function ────────────────────────────────────────────────

def score_topic(
    title: str,
    content: str = "",
    weight_mode: str = "new_account",
    platform: str = "wechat",
    positioning: str = "business_tech",
    use_llm: bool = False,
    llm_callable: callable = None,
) -> ScoreResult:
    """
    Score a topic across all 5 dimensions and return weighted result.

    Args:
        title: Topic title
        content: Topic body/description (raw_content)
        weight_mode: 'new_account' or 'old_account'
        platform: 'wechat', 'toutiao', or 'xiaohongshu'
        positioning: 'business_tech' or 'entertainment'
        use_llm: If True, use LLM for dimension scores instead of rules
        llm_callable: Async function (title, content) -> DimensionScores (only used if use_llm=True)
    """
    is_entertainment = positioning == "entertainment"

    # Step 1: Dimension scoring — use appropriate scorer set
    scorers = SCORERS_ENTERTAINMENT if is_entertainment else SCORERS
    dimensions = DimensionScores(
        relevance=scorers["relevance"](title, content),
        timeliness=scorers["timeliness"](title, content),
        value=scorers["value"](title, content),
        compliance=scorers["compliance"](title, content),
        competition=scorers["competition"](title, content),
    )

    # Step 2: Weighted total — use appropriate weight table
    weights_table = WEIGHTS_ENTERTAINMENT if is_entertainment else WEIGHTS
    weights = weights_table.get(weight_mode, weights_table["new_account"]).get(
        platform, weights_table["new_account"]["wechat"]
    )
    weighted_total = (
        dimensions.relevance * weights["relevance"]
        + dimensions.timeliness * weights["timeliness"]
        + dimensions.value * weights["value"]
        + dimensions.compliance * weights["compliance"]
        + dimensions.competition * weights["competition"]
    )

    # Step 3: Bonus/penalty adjustments
    if is_entertainment:
        delta, bonus_details = _apply_bonus_penalty_entertainment(title, content, weight_mode)
    else:
        delta, bonus_details = _apply_bonus_penalty(title, content, weight_mode)
    final_total = max(0.0, min(100.0, weighted_total + delta))

    # Step 4: Grade
    grade = _grade(final_total)

    # Step 5: Fast-track LLM override if requested
    if use_llm and llm_callable:
        logger.info("LLM scoring requested for topic: %s", title[:50])

    return ScoreResult(
        relevance_score=round(dimensions.relevance, 1),
        timeliness_score=round(dimensions.timeliness, 1),
        value_score=round(dimensions.value, 1),
        compliance_score=round(dimensions.compliance, 1),
        competition_score=round(dimensions.competition, 1),
        total_score=round(final_total, 1),
        grade=grade,
        bonus_details=json.dumps(bonus_details, ensure_ascii=False),
        weight_mode=weight_mode,
        platform=platform,
        positioning=positioning,
    )


def get_weights() -> dict:
    return WEIGHTS


def get_platform_label(platform_key: str) -> str:
    return PLATFORM_LABELS.get(platform_key, platform_key)

"""Comprehensive test suite for the topic selection system.

Covers:
  1. Unit tests: scoring engine (dimensions, weights, bonus/penalty, edge cases)
  2. Unit tests: matching engine (rule-based, field overlap, DNA richness)
  3. API integration tests: CRUD, scoring, matching, pipeline, review flow
  4. Edge cases: empty content, very long text, special characters, concurrent scoring
  5. Weight mode / platform switching
  6. Status flow correctness

Usage:
  cd select_topic && python3 -m pytest test_suite.py -v -s
"""

from __future__ import annotations

import json
import math
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# ── Core module imports ──────────────────────────────────────────────────
from core.models import (
    TopicCreate, Topic, ScoreResult, MatchResult, ReviewAction,
    ReviewLog, CelebritySummary, CelebrityDNA, DimensionScores,
    PipelineRequest, ScoreRequest, MatchRequest,
)
from core.scoring_engine import (
    score_topic, _score_relevance, _score_timeliness, _score_value,
    _score_compliance, _score_competition, _apply_bonus_penalty,
    _score_relevance_entertainment, _score_timeliness_entertainment,
    _score_value_entertainment, _score_compliance_entertainment,
    _score_competition_entertainment, _apply_bonus_penalty_entertainment,
    _grade, WEIGHTS, WEIGHTS_ENTERTAINMENT, SCORERS, SCORERS_ENTERTAINMENT,
    get_platform_label, POSITIONING,
)
from core.matching_engine import (
    match_celebrities_rule_based, _format_celebrity_for_prompt,
    MATCHING_PROMPT,
)
from core.collector.direct_scraper import (
    DEFAULT_PLATFORMS, SCRAPERS, _parse_html_hot_items, _parse_json_hot_items,
)

# ── Test data ────────────────────────────────────────────────────────────

TOPIC_AI = ("OpenAI发布GPT-5：多模态大模型全面升级，AI行业迎来新纪元",
            "今天OpenAI正式发布了GPT-5，这是一个多模态大模型，支持视频、音频、图像和文本的全模态理解与生成。业内人士分析，这将彻底改变AI应用的底层逻辑，对各行各业产生深远影响。本文从三个维度深度解读：技术突破、商业模式和普通人机会。")

TOPIC_TESLA = ("特斯拉FSD入华获批，自动驾驶行业迎来转折点",
               "近日，特斯拉FSD（全自动驾驶）正式获得中国监管部门批准，即将在国内落地。这一事件标志着中国自动驾驶行业进入新阶段。本文复盘自动驾驶技术发展脉络，分析FSD入华对国产新能源车企的影响，并给出普通投资者的避坑指南。")

TOPIC_GOSSIP = ("周末吃瓜：某明星离婚内幕曝光，粉丝集体应援",
                "据知情人透露，娱乐圈某顶流明星与配偶离婚内幕曝光，涉及出轨和财产分割争议。粉丝纷纷在社交平台应援。这起八卦事件引发网络热议，网友吃瓜不断。")

TOPIC_FINANCE = ("蚂蚁集团重启IPO传闻引发市场关注，金融科技监管环境变化",
                 "据最新消息，蚂蚁集团正在重新启动IPO进程。在经历了监管整改后，金融科技行业环境发生重大变化。本文分析蚂蚁重启IPO的深层原因，以及对中国数字经济监管的长期影响。")

TOPIC_SHALLOW = ("快讯：苹果发布新款iPhone", "苹果公司今日发布了新款iPhone手机。")

TOPIC_OLD = ("上月新能源车销量数据公布，比亚迪保持领先",
             "上周公布的行业数据显示，上月国内新能源车销量同比增长30%，比亚迪继续保持市场领先地位。")

TOPIC_DEEP = ("大模型时代的创业方法论：从底层逻辑到落地实操",
              "本文总结了大模型时代创业的核心方法论，包括技术选型框架、团队搭建模型、产品策略和商业模式设计。结合5个真实案例，给出普通人也能上手的实操指南，帮助创业者避坑。")

TOPIC_SENSITIVE = ("某虚拟币即将暴涨，炒币荐股诈骗套路大揭秘",
                   "本文将曝光最新的炒币诈骗手法，涉及虚拟币、荐股、投资建议等高风险内容。")

# ── Entertainment / 鸡汤 test data ──────────────────────────────────────

TOPIC_VARIETY = ("《乘风破浪》姐姐们的情感故事刷屏全网，这次节目中姐姐们的真实经历让人感动落泪",
                 "最近热播的综艺节目《乘风破浪》第五季中，多位姐姐在节目中分享了自己真实的人生经历，内容饱满感人。她们的故事包括婚姻危机、职场挫折、育儿心得等，引发了全民大讨论，各大社交平台热议不断。这档节目不仅给观众带来了感动，更让人思考女性自我成长的价值。")

TOPIC_CHICKEN_SOUP = ("刚刚看到的治愈系故事：一个普通人如何通过每天一个小改变，逆袭成为更好的自己",
                      "今天刷到一个特别暖心的故事。主人公从最普通的上班族做起，每天坚持一个小习惯改变，五年后完全蜕变。他分享了具体的实操方法，包括时间管理技巧、情绪调节心得、人际关系维护锦囊等，非常实用。这篇文章在朋友圈被疯狂转发，很多人表示很受启发。评论区网友都在说看哭了又看笑了。")

TOPIC_GOSSIP_ENT = ("周末吃瓜：某顶流明星离婚内幕被曝光，粉丝互撕疯狂应援",
                    "据知情人士爆料，娱乐圈某顶流明星与配偶离婚内幕震惊全网，涉及出轨和大量财产分割争议。双方粉丝在社交平台互相攻击应援不断，这场娱乐圈大事件再次刷新网友认知。")

TOPIC_SHALLOW_ENT = ("快讯：某明星发了一张自拍", "今日某知名明星在社交平台发布了一张自拍照，粉丝纷纷点赞。")

TOPIC_UNIQUE_VIEW = ("独家角度解读《流浪地球3》：这部冷门佳片的另类视角让人耳目一新",
                     "不同于大众的常规影评，本文从独特角度切入解读《流浪地球3》。作者挖掘了被人忽视的细节，提出了令人耳目一新的观点，称其为被大众低估的冷门佳作。全文分析鞭辟入里，情感共鸣强烈。")

TOPIC_ENT_LOW_RISK = ("正能量！某明星原创声明：用真实经历传递温暖",
                      "近日，某知名艺人发布原创声明，分享了自己的真实经历，传达出积极向上的生活态度。该艺人强调内容为本人亲历，经当事人授权发布，希望传递正能量。网友们纷纷被这份真诚感动，评论数很快破万。")


# ═══════════════════════════════════════════════════════════════════════════
# Collector parsing tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCollectorSources:
    def test_new_sources_registered(self):
        assert "newrank" in DEFAULT_PLATFORMS
        assert "tophub" in DEFAULT_PLATFORMS
        assert "newrank" in SCRAPERS
        assert "tophub" in SCRAPERS

    def test_parse_json_hot_items_nested_payload(self):
        payload = {
            "data": {
                "list": [
                    {"title": "OpenAI发布新模型引发行业热议", "url": "/a/1", "rank": 1, "heat": 98888},
                    {"name": "国产大模型融资刷新纪录", "link": "https://example.com/a/2", "index": 2},
                ]
            }
        }
        items = _parse_json_hot_items(payload, "newrank", "https://www.newrank.cn", limit=10)
        assert [i.title for i in items] == ["OpenAI发布新模型引发行业热议", "国产大模型融资刷新纪录"]
        assert items[0].url == "https://www.newrank.cn/a/1"
        assert items[0].platform == "newrank"
        assert items[0].heat_score == 100.0

    def test_parse_html_hot_items_filters_navigation(self):
        html = """
        <nav><a href="/login">登录</a><a href="/about">关于我们</a></nav>
        <main>
          <a href="/n/1">AI创业公司估值暴涨，资本重新涌入</a>
          <a href="https://example.com/n/2" title="新能源车企降价潮继续发酵">查看</a>
        </main>
        """
        items = _parse_html_hot_items(html, "tophub", "https://tophub.today", limit=10)
        assert [i.title for i in items] == ["AI创业公司估值暴涨，资本重新涌入", "新能源车企降价潮继续发酵"]
        assert items[0].url == "https://tophub.today/n/1"
        assert items[1].url == "https://example.com/n/2"


# ═══════════════════════════════════════════════════════════════════════════
# 1. Unit tests — Scoring Engine
# ═══════════════════════════════════════════════════════════════════════════

class TestDimensionRelevance:
    def test_strong_relevance_ai_topic(self):
        score = _score_relevance(*TOPIC_AI)
        assert score >= 80, f"AI topic should score high, got {score}"

    def test_moderate_relevance_tesla(self):
        score = _score_relevance(*TOPIC_TESLA)
        assert score >= 75, f"Tesla topic should score moderate-high, got {score}"

    def test_low_relevance_gossip(self):
        score = _score_relevance(*TOPIC_GOSSIP)
        assert score <= 45, f"Gossip should score low due to negative keywords, got {score}"

    def test_finance_relevance(self):
        score = _score_relevance(*TOPIC_FINANCE)
        assert score >= 75, f"Finance topic should score high, got {score}"

    def test_empty_content_relevance(self):
        score = _score_relevance("", "")
        assert score == 30.0, f"Empty content should get default 30, got {score}"

    def test_secondary_only_relevance(self):
        score = _score_relevance("职场创业的商业模式分析", "")
        assert score >= 50, f"Secondary keywords should score >= 50, got {score}"

    def test_neg3_words_drops_to_20(self):
        score = _score_relevance("吃瓜：某明星离婚出轨绯闻八卦", "")
        assert score == 20.0, f"3+ negative keywords → 20, got {score}"

    def test_neg2_words_drops_to_30(self):
        score = _score_relevance("某偶像粉丝", "")
        assert score == 30.0, f"2 negative keywords → 30, got {score}"

    def test_neg1_word_drops_to_45(self):
        score = _score_relevance("某明星", "")
        assert score == 45.0, f"1 negative keyword → 45, got {score}"


class TestDimensionTimeliness:
    def test_just_now(self):
        assert _score_timeliness("刚刚突发新闻", "") == 95.0

    def test_today(self):
        assert _score_timeliness("今天早上大事件", "") == 92.0

    def test_yesterday(self):
        assert _score_timeliness("昨天发布了新政策", "") == 85.0

    def test_this_week(self):
        assert _score_timeliness("近日行业动态汇总", "") == 78.0

    def test_last_week(self):
        assert _score_timeliness("上周市场回顾", "") == 60.0

    def test_dated(self):
        assert _score_timeliness("2024年3月15日事件回顾", "") == 55.0

    def test_hot_indicator(self):
        assert _score_timeliness("热搜话题刷屏", "") == 82.0

    def test_default_timeliness(self):
        assert _score_timeliness("一些普通话题", "") == 50.0


class TestDimensionValue:
    def test_deep_content(self):
        score = _score_value(*TOPIC_DEEP)
        assert score >= 85, f"Deep topic should score >= 85, got {score}"

    def test_shallow_content(self):
        score = _score_value(*TOPIC_SHALLOW)
        assert score <= 55, f"Shallow topic should score <= 55, got {score}"

    def test_empty_value(self):
        score = _score_value("", "")
        assert score == 55.0  # default for no content

    def test_long_content_boost(self):
        long_content = "x" * 600
        score = _score_value("普通话题", long_content)
        assert score >= 65, f"Long content should get >= 65, got {score}"


class TestDimensionCompliance:
    def test_clean_topic(self):
        score = _score_compliance(*TOPIC_AI)
        assert score >= 80, f"Clean AI topic should score >= 80, got {score}"

    def test_sensitive_topic(self):
        score = _score_compliance(*TOPIC_SENSITIVE)
        assert score < 50, f"Sensitive topic should score < 50, got {score}"

    def test_high_risk_keyword(self):
        score = _score_compliance("这个政策是造谣诈骗", "")
        assert score <= 35, f"High-risk keywords should score <= 35, got {score}"

    def test_low_risk_indicators(self):
        score = _score_compliance("官方公告发布最新财报数据来源可靠", "")
        assert score >= 88, f"Low-risk indicators should score >= 88, got {score}"

    def test_default_compliance(self):
        score = _score_compliance("普通话题", "")
        assert score == 85.0


class TestDimensionCompetition:
    def test_niche_topic(self):
        score = _score_competition("蓝海独家分析：垂直细分领域", "")
        assert score >= 85, f"Niche topic should score >= 85, got {score}"

    def test_red_ocean(self):
        score = _score_competition("刷屏了！大家都在说这个热议话题", "")
        assert score <= 55, f"Red ocean should score <= 55, got {score}"

    def test_default_competition(self):
        score = _score_competition("普通话题", "")
        assert score == 68.0


# ═══════════════════════════════════════════════════════════════════════════
# 2. Unit tests — Bonus / Penalty
# ═══════════════════════════════════════════════════════════════════════════

class TestBonusPenalty:
    def test_ai_bonus(self):
        delta, details = _apply_bonus_penalty(*TOPIC_AI, weight_mode="new_account")
        assert delta > 0, f"AI topic should get bonus, got {delta}"
        bonus_names = [d["name"] for d in details if d["type"] == "bonus"]
        assert any("AI" in n for n in bonus_names), f"Should have AI bonus in {bonus_names}"

    def test_bonus_capped_at_10(self):
        # Craft text that would trigger many bonuses
        text = "AI人工智能大模型GPT融资IPO上市 财报战略 新规政策新能源启发思维方法论 官方公告热搜"
        delta, details = _apply_bonus_penalty(text, "", weight_mode="new_account")
        bonus_sum = sum(d["points"] for d in details if d["type"] == "bonus")
        # Raw bonus sum may exceed 10, but final delta applies the cap
        penalty_sum = sum(d["points"] for d in details if d["type"] == "penalty")
        # The cap is applied to bonus_total before adding penalty
        capped_bonus = min(bonus_sum, 10.0)
        expected_delta = capped_bonus + penalty_sum
        assert delta == expected_delta, f"delta={delta} should be capped_bonus({capped_bonus}) + penalty({penalty_sum})"
        assert capped_bonus <= 10.0, f"Capped bonus should be <= 10, got {capped_bonus}"

    def test_penalty_pure_news(self):
        delta, details = _apply_bonus_penalty("纯资讯新闻转：分享转发", "", weight_mode="new_account")
        penalties = [d for d in details if d["type"] == "penalty"]
        assert len(penalties) >= 1, "Should have penalty for pure news"

    def test_penalty_expired(self):
        delta, details = _apply_bonus_penalty("上月发布的过期内股票理财", "", weight_mode="new_account")
        penalties = [d for d in details if d["type"] == "penalty"]
        assert len(penalties) >= 1, "Should have penalties"

    def test_new_account_extra_bonus(self):
        delta_new, _ = _apply_bonus_penalty("新手快速入门基础知识", "", weight_mode="new_account")
        delta_old, _ = _apply_bonus_penalty("新手快速入门基础知识", "", weight_mode="old_account")
        assert delta_new > delta_old, f"New account should get extra bonus, new={delta_new} old={delta_old}"

    def test_new_account_extra_penalty(self):
        """New account penalizes high-barrier professional content."""
        delta, details = _apply_bonus_penalty("数据复盘高阶深度分析复杂模型专业壁垒", "", weight_mode="new_account")
        penalties = [d for d in details if d["type"] == "penalty"]
        assert any("新号" in d["name"] for d in penalties), f"Should have new-account penalty in {penalties}"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Unit tests — Main Scoring Function
# ═══════════════════════════════════════════════════════════════════════════

class TestScoreTopic:
    def test_ai_topic_s_or_a(self):
        result = score_topic(*TOPIC_AI, weight_mode="new_account", platform="wechat")
        assert result.total_score >= 80, f"AI topic should be A or S, got {result.grade}/{result.total_score}"
        assert result.grade in ("S", "A")

    def test_gossip_topic_c(self):
        result = score_topic(*TOPIC_GOSSIP, weight_mode="new_account", platform="wechat")
        assert result.grade == "C", f"Gossip should be C, got {result.grade}/{result.total_score}"

    def test_weight_mode_affects_score(self):
        r_new = score_topic(*TOPIC_TESLA, weight_mode="new_account", platform="toutiao")
        r_old = score_topic(*TOPIC_TESLA, weight_mode="old_account", platform="toutiao")
        assert r_new.total_score != r_old.total_score, \
            f"Different weight modes should produce different scores: new={r_new.total_score} old={r_old.total_score}"

    def test_platform_affects_score(self):
        r_wx = score_topic(*TOPIC_AI, weight_mode="new_account", platform="wechat")
        r_xhs = score_topic(*TOPIC_AI, weight_mode="new_account", platform="xiaohongshu")
        assert r_wx.total_score != r_xhs.total_score, \
            f"Different platforms should produce different scores: wx={r_wx.total_score} xhs={r_xhs.total_score}"

    def test_all_dimensions_present(self):
        result = score_topic(*TOPIC_AI, weight_mode="new_account", platform="wechat")
        assert result.relevance_score > 0
        assert result.timeliness_score > 0
        assert result.value_score > 0
        assert result.compliance_score > 0
        assert result.competition_score > 0
        assert result.total_score > 0
        assert result.grade in ("S", "A", "B", "C")
        assert result.weight_mode == "new_account"
        assert result.platform == "wechat"
        assert result.bonus_details  # JSON string, not empty

    def test_score_with_empty_content(self):
        result = score_topic("一个普通话题", "", weight_mode="new_account", platform="wechat")
        assert result.total_score >= 0
        assert result.total_score <= 100

    def test_score_very_long_title(self):
        long_title = "这是一个非常长的标题" * 50  # ~500 chars
        result = score_topic(long_title, "", weight_mode="new_account", platform="wechat")
        assert 0 <= result.total_score <= 100

    def test_special_characters_in_title(self):
        result = score_topic("AI & ML: The Future of Tech™ — 2024©", "content with <html> tags & stuff")
        assert 0 <= result.total_score <= 100

    def test_total_score_range(self):
        """All scores must be in 0-100 range."""
        cases = [TOPIC_AI, TOPIC_TESLA, TOPIC_GOSSIP, TOPIC_FINANCE, TOPIC_SHALLOW,
                 TOPIC_DEEP, TOPIC_OLD, TOPIC_SENSITIVE]
        for title, content in cases:
            result = score_topic(title, content)
            assert 0.0 <= result.total_score <= 100.0, \
                f"Score {result.total_score} out of range for: {title[:30]}"

    def test_grade_thresholds(self):
        assert _grade(95) == "S"
        assert _grade(90) == "S"
        assert _grade(89.9) == "A"
        assert _grade(80) == "A"
        assert _grade(79.9) == "B"
        assert _grade(70) == "B"
        assert _grade(69.9) == "C"
        assert _grade(0) == "C"

    def test_all_weight_mode_platform_combos(self):
        """Every weight_mode × platform combo should produce a valid score."""
        for mode in ("new_account", "old_account"):
            for plat in ("wechat", "toutiao", "xiaohongshu"):
                result = score_topic(*TOPIC_AI, weight_mode=mode, platform=plat)
                assert 0 <= result.total_score <= 100, \
                    f"Invalid score for {mode}/{plat}: {result.total_score}"
                assert result.weight_mode == mode
                assert result.platform == plat

    def test_get_weights(self):
        w = WEIGHTS
        assert "new_account" in w
        assert "old_account" in w
        for mode in w:
            assert "wechat" in w[mode]
            assert "toutiao" in w[mode]
            assert "xiaohongshu" in w[mode]
            # Each platform must have all 5 dimensions
            for plat in w[mode]:
                dims = w[mode][plat]
                for dim in ("relevance", "timeliness", "value", "compliance", "competition"):
                    assert dim in dims, f"Missing {dim} in {mode}/{plat}"

    def test_platform_labels(self):
        assert get_platform_label("wechat") == "公众号"
        assert get_platform_label("toutiao") == "今日头条"
        assert get_platform_label("xiaohongshu") == "小红书"
        assert get_platform_label("unknown") == "unknown"

    def test_bonus_details_valid_json(self):
        result = score_topic(*TOPIC_AI)
        details = json.loads(result.bonus_details)
        assert isinstance(details, list)
        for item in details:
            assert "type" in item
            assert "name" in item
            assert "points" in item
            assert item["type"] in ("bonus", "penalty")


# ═══════════════════════════════════════════════════════════════════════════
# 3b. Unit tests — Entertainment/鸡汤 Scoring Engine
# ═══════════════════════════════════════════════════════════════════════════

class TestEntertainmentDimensions:
    def test_relevance_entertainment_high(self):
        score = _score_relevance_entertainment(*TOPIC_VARIETY)
        assert score >= 75, f"Variety show topic should score high in entertainment, got {score}"

    def test_relevance_entertainment_chicken_soup(self):
        score = _score_relevance_entertainment(*TOPIC_CHICKEN_SOUP)
        assert score >= 65, f"Chicken soup topic should score moderate-high in entertainment, got {score}"

    def test_relevance_entertainment_gossip(self):
        score = _score_relevance_entertainment(*TOPIC_GOSSIP_ENT)
        assert score >= 75, f"Entertainment gossip should score high in entertainment mode, got {score}"

    def test_relevance_entertainment_low_for_business(self):
        """A tech/business topic should score lower in entertainment relevance."""
        business_score = _score_relevance_entertainment(*TOPIC_AI)
        assert business_score < 55, f"AI business topic should score low in entertainment relevance, got {business_score}"

    def test_timeliness_entertainment_hot(self):
        score = _score_timeliness_entertainment("刚刚热播的综艺节目", "")
        assert score >= 90, f"Hot show should score high, got {score}"

    def test_timeliness_entertainment_date(self):
        score = _score_timeliness_entertainment("去年的综艺回顾", "")
        assert score == 55.0, f"Old content should score 55, got {score}"

    def test_value_entertainment_deep(self):
        score = _score_value_entertainment(*TOPIC_CHICKEN_SOUP)
        assert score >= 78, f"Emotional chicken soup should have high value, got {score}"

    def test_value_entertainment_shallow(self):
        score = _score_value_entertainment(*TOPIC_SHALLOW_ENT)
        assert score < 60, f"Shallow celebrity post should have low value, got {score}"

    def test_compliance_entertainment_clean(self):
        score = _score_compliance_entertainment(*TOPIC_ENT_LOW_RISK)
        assert score >= 85, f"Clean entertainment topic should score high, got {score}"

    def test_compliance_entertainment_risky(self):
        score = _score_compliance_entertainment("偷拍明星隐私造谣诽谤", "")
        assert score <= 35, f"Privacy violation should score low, got {score}"

    def test_competition_entertainment_niche(self):
        score = _score_competition_entertainment(*TOPIC_UNIQUE_VIEW)
        assert score >= 85, f"Unique angle should be blue ocean, got {score}"

    def test_competition_entertainment_red_ocean(self):
        score = _score_competition_entertainment("大众热议的全网刷屏话题", "")
        assert score <= 55, f"Red ocean topic should score low, got {score}"


class TestEntertainmentBonusPenalty:
    def test_emotional_resonance_bonus(self):
        text = "今天看到一个感人的独家故事，特别暖心治愈，让人泪目共鸣"
        delta, details = _apply_bonus_penalty_entertainment(text, "", weight_mode="new_account")
        assert delta > 0, f"Should get bonuses, got {delta}"
        bonus_names = [d["name"] for d in details if d["type"] == "bonus"]
        assert any("情感" in n for n in bonus_names), f"Should have emotional bonus in {bonus_names}"

    def test_celebrity_bonus(self):
        delta, details = _apply_bonus_penalty_entertainment("明星专访", "独家明星访谈内容", weight_mode="new_account")
        bonus_names = [d["name"] for d in details if d["type"] == "bonus"]
        assert any("明星" in n or "名人" in n for n in bonus_names), f"Should have celebrity bonus in {bonus_names}"

    def test_bonus_capped_at_10(self):
        text = "独家明星正能量 技巧方法教程 治愈温暖感动评论过万 热门刷屏简单轻松"
        delta, details = _apply_bonus_penalty_entertainment(text, "", weight_mode="new_account")
        bonus_sum = sum(d["points"] for d in details if d["type"] == "bonus")
        penalty_sum = sum(d["points"] for d in details if d["type"] == "penalty")
        capped_bonus = min(bonus_sum, 10.0)
        expected_delta = capped_bonus + penalty_sum
        assert delta == expected_delta, f"delta={delta} should be capped_bonus({capped_bonus}) + penalty({penalty_sum})"

    def test_penalty_copycat(self):
        delta, details = _apply_bonus_penalty_entertainment("纯搬运转载内容", "", weight_mode="new_account")
        penalties = [d for d in details if d["type"] == "penalty"]
        assert len(penalties) >= 1, "Should have penalty for copying"

    def test_penalty_vulgar(self):
        delta, details = _apply_bonus_penalty_entertainment("低俗擦边大尺度内容", "", weight_mode="new_account")
        penalties = [d for d in details if d["type"] == "penalty"]
        assert any("低俗" in d["name"] for d in penalties), f"Should have vulgar penalty in {penalties}"

    def test_new_account_extra_bonus(self):
        delta_new, _ = _apply_bonus_penalty_entertainment("简单日常随手技巧", "", weight_mode="new_account")
        delta_old, _ = _apply_bonus_penalty_entertainment("简单日常随手技巧", "", weight_mode="old_account")
        assert delta_new > delta_old, f"New account should get extra bonus: new={delta_new} old={delta_old}"

    def test_new_account_high_barrier_penalty(self):
        delta, details = _apply_bonus_penalty_entertainment("专业设备专业摄影团队制作复杂剪辑", "", weight_mode="new_account")
        penalties = [d for d in details if d["type"] == "penalty"]
        assert any("新号" in d["name"] for d in penalties), f"Should have new-account penalty in {penalties}"


class TestScoreTopicEntertainment:
    def test_variety_topic_high_score(self):
        result = score_topic(*TOPIC_VARIETY, weight_mode="new_account", platform="wechat", positioning="entertainment")
        assert result.total_score >= 75, f"Variety show should score high in entertainment, got {result.grade}/{result.total_score}"
        assert result.positioning == "entertainment"

    def test_chicken_soup_high_score(self):
        result = score_topic(*TOPIC_CHICKEN_SOUP, weight_mode="new_account", platform="wechat", positioning="entertainment")
        assert result.total_score >= 75, f"Chicken soup should score high in entertainment, got {result.grade}/{result.total_score}"

    def test_business_topic_low_in_entertainment(self):
        result = score_topic(*TOPIC_AI, weight_mode="new_account", platform="wechat", positioning="entertainment")
        assert result.total_score < 75, f"AI topic should score lower in entertainment, got {result.total_score}"

    def test_same_topic_different_positioning(self):
        """The same topic should get different scores in different positioning modes."""
        r_biz = score_topic(*TOPIC_AI, weight_mode="new_account", platform="wechat", positioning="business_tech")
        r_ent = score_topic(*TOPIC_AI, weight_mode="new_account", platform="wechat", positioning="entertainment")
        assert r_biz.total_score != r_ent.total_score, \
            f"Same AI topic should differ: biz={r_biz.total_score} ent={r_ent.total_score}"

    def test_gossip_entertainment_vs_business(self):
        """Gossip should score higher in entertainment than in business mode."""
        r_biz = score_topic(*TOPIC_GOSSIP, weight_mode="new_account", platform="wechat", positioning="business_tech")
        r_ent = score_topic(*TOPIC_GOSSIP, weight_mode="new_account", platform="wechat", positioning="entertainment")
        assert r_ent.total_score > r_biz.total_score, \
            f"Gossip should be higher in entertainment: biz={r_biz.total_score} ent={r_ent.total_score}"

    def test_all_entertainment_weight_mode_combos(self):
        for mode in ("new_account", "old_account"):
            for plat in ("wechat", "toutiao", "xiaohongshu"):
                result = score_topic(*TOPIC_VARIETY, weight_mode=mode, platform=plat, positioning="entertainment")
                assert 0 <= result.total_score <= 100, f"Invalid score for {mode}/{plat}: {result.total_score}"
                assert result.positioning == "entertainment"

    def test_entertainment_bonus_details_valid_json(self):
        result = score_topic(*TOPIC_VARIETY, positioning="entertainment")
        details = json.loads(result.bonus_details)
        assert isinstance(details, list)
        for item in details:
            assert "type" in item
            assert "name" in item
            assert "points" in item
            assert item["type"] in ("bonus", "penalty")

    def test_positioning_defaults_to_business_tech(self):
        result = score_topic("普通话题", "")
        assert result.positioning == "business_tech"

    def test_entertainment_positioning_in_result(self):
        result = score_topic(*TOPIC_CHICKEN_SOUP, positioning="entertainment")
        assert result.positioning == "entertainment"

    def test_positioning_config(self):
        assert POSITIONING["business_tech"] == "商业科技"
        assert POSITIONING["entertainment"] == "娱乐鸡汤"

    def test_entertainment_weights_structure(self):
        """All 6 entertainment weight combos must be valid."""
        w = WEIGHTS_ENTERTAINMENT
        assert "new_account" in w
        assert "old_account" in w
        for mode in w:
            assert "wechat" in w[mode]
            assert "toutiao" in w[mode]
            assert "xiaohongshu" in w[mode]
            for plat in w[mode]:
                dims = w[mode][plat]
                for dim in ("relevance", "timeliness", "value", "compliance", "competition"):
                    assert dim in dims, f"Missing {dim} in entertainment {mode}/{plat}"

    def test_entertainment_scorers_all_present(self):
        for dim in ("relevance", "timeliness", "value", "compliance", "competition"):
            assert dim in SCORERS_ENTERTAINMENT, f"Missing {dim} in SCORERS_ENTERTAINMENT"
            assert callable(SCORERS_ENTERTAINMENT[dim])


# ═══════════════════════════════════════════════════════════════════════════
# 4. Unit tests — Matching Engine (Rule-Based)
# ═══════════════════════════════════════════════════════════════════════════

class TestRuleBasedMatching:
    @pytest.mark.asyncio
    async def test_matches_return_top3(self):
        matches = await match_celebrities_rule_based("AI人工智能大模型GPT", "科技前沿话题", top_n=3)
        assert len(matches) == 3, f"Should return 3 matches, got {len(matches)}"

    @pytest.mark.asyncio
    async def test_matches_have_required_fields(self):
        matches = await match_celebrities_rule_based("AI人工智能", "")
        for m in matches:
            assert m.celebrity_id, "celebrity_id required"
            assert m.celebrity_name, "celebrity_name required"
            assert 0 <= m.match_score <= 100, f"match_score out of range: {m.match_score}"
            assert m.match_reason, "match_reason required"
            assert m.rank >= 1, f"rank should be >= 1, got {m.rank}"

    @pytest.mark.asyncio
    async def test_matches_sorted_by_score(self):
        matches = await match_celebrities_rule_based("AI大模型科技商业分析", "")
        scores = [m.match_score for m in matches]
        assert scores == sorted(scores, reverse=True), f"Results not sorted: {scores}"

    @pytest.mark.asyncio
    async def test_ranks_sequential(self):
        matches = await match_celebrities_rule_based("AI人工智能", "")
        for i, m in enumerate(matches):
            assert m.rank == i + 1, f"Rank expected {i+1} got {m.rank}"

    @pytest.mark.asyncio
    async def test_relevant_topic_higher_scores(self):
        """A clearly tech topic should produce higher match scores than gossip."""
        tech_matches = await match_celebrities_rule_based("AI大模型科技商业分析投资", "")
        gossip_matches = await match_celebrities_rule_based("娱乐圈明星八卦吃瓜离婚", "")
        tech_top = tech_matches[0].match_score
        gossip_top = gossip_matches[0].match_score
        assert tech_top >= gossip_top, \
            f"Tech topic top score ({tech_top}) should >= gossip ({gossip_top})"

    @pytest.mark.asyncio
    async def test_different_topics_produce_different_scores(self):
        """Different topics should NOT all get identical scores."""
        topics = ["AI大模型技术趋势", "娱乐圈八卦新闻", "新能源车市场分析", "金融科技监管"]
        all_scores = []
        for t in topics:
            matches = await match_celebrities_rule_based(t, "")
            all_scores.append((t, [m.match_score for m in matches]))
        # At least some variability expected
        unique_tops = len(set(s[1][0] for s in all_scores))
        assert unique_tops >= 2, f"Expected at least 2 distinct top scores, got {unique_tops}: {all_scores}"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Unit tests — Models
# ═══════════════════════════════════════════════════════════════════════════

class TestModels:
    def test_topic_create_validation(self):
        t = TopicCreate(title="测试话题")
        assert t.title == "测试话题"
        assert t.source_type == "manual"
        assert t.heat_level == "normal"

    def test_score_result_defaults(self):
        s = ScoreResult()
        assert s.topic_id == ""
        assert s.grade == "C"
        assert s.weight_mode == "new_account"
        assert s.platform == "wechat"
        assert s.bonus_details == "[]"

    def test_match_result_defaults(self):
        m = MatchResult(celebrity_id="c1", celebrity_name="test")
        assert m.topic_id == ""
        assert m.match_score == 0.0
        assert m.rank == 0

    def test_review_action_defaults(self):
        r = ReviewAction()
        assert r.action == "confirm"
        assert r.note == ""

    def test_celebrity_dna_structure(self):
        dna = CelebrityDNA(id="c1", name="测试名人")
        assert dna.id == "c1"
        assert dna.name == "测试名人"
        assert dna.fields == []
        assert dna.expression_dna == {}
        assert dna.thinking_tools == {}
        assert dna.decision_rules == {}
        assert dna.worldview == {}
        assert dna.boundaries_evolution == {}
        assert dna.suggested_topics == []

    def test_dimension_scores(self):
        dims = DimensionScores(relevance=85, timeliness=70, value=80, compliance=90, competition=60)
        assert dims.relevance == 85
        assert dims.competition == 60

    def test_pipeline_request(self):
        pr = PipelineRequest(title="test")
        assert pr.weight_mode == "new_account"
        assert pr.platform == "wechat"

    def test_score_request(self):
        sr = ScoreRequest()
        assert sr.weight_mode == "new_account"
        assert sr.platform == "wechat"
        assert sr.use_llm is False

    def test_match_request(self):
        mr = MatchRequest()
        assert mr.use_llm is True


# ═══════════════════════════════════════════════════════════════════════════
# 6. Integration tests — FastAPI endpoints
# ═══════════════════════════════════════════════════════════════════════════

from fastapi.testclient import TestClient
from server.app import app
from server.database import get_db_path

client = TestClient(app)


class TestAPIHealth:
    def test_celebrity_list(self):
        resp = client.get("/api/celebrities")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1, "Should have at least 1 celebrity"
        for c in data:
            assert "id" in c
            assert "name" in c

    def test_celebrity_detail(self):
        """Fetch a single celebrity by ID."""
        list_resp = client.get("/api/celebrities")
        celebs = list_resp.json()
        if celebs:
            cid = celebs[0]["id"]
            resp = client.get(f"/api/celebrities/{cid}")
            assert resp.status_code == 200, resp.text
            detail = resp.json()
            assert detail["id"] == cid

    def test_celebrity_not_found(self):
        resp = client.get("/api/celebrities/nonexistent-id")
        assert resp.status_code == 404

    def test_get_weights(self):
        resp = client.get("/api/config/weights")
        assert resp.status_code == 200
        data = resp.json()
        assert "new_account" in data or "old_account" in data

    def test_update_weights(self):
        new_weights = {
            "new_account": {
                "wechat": {"relevance": 0.5, "timeliness": 0.2, "value": 0.1, "compliance": 0.1, "competition": 0.1},
            }
        }
        resp = client.put("/api/config/weights", json=new_weights)
        assert resp.status_code == 200
        # Verify updated
        resp2 = client.get("/api/config/weights")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["new_account"]["wechat"]["relevance"] == 0.5

    def test_get_rating_thresholds(self):
        resp = client.get("/api/config/rating-thresholds")
        assert resp.status_code == 200
        data = resp.json()
        assert "S" in data


class TestTopicCRUD:
    def test_create_topic(self):
        resp = client.post("/api/topics", json={
            "title": "测试话题：AI技术突破",
            "raw_content": "这是一个关于AI技术突破的测试内容",
            "source_url": "https://example.com/article",
            "heat_level": "high",
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "id" in data
        assert data["title"] == "测试话题：AI技术突破"
        assert data["status"] == "pending"
        return data["id"]

    def test_create_topic_minimal(self):
        resp = client.post("/api/topics", json={"title": "最小测试话题"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_list_topics(self):
        resp = client.get("/api/topics")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_topics_with_status_filter(self):
        resp = client.get("/api/topics?status=pending")
        assert resp.status_code == 200

    def test_list_topics_with_search(self):
        resp = client.get("/api/topics?search=AI")
        assert resp.status_code == 200

    def test_get_single_topic(self):
        # First create one
        create_resp = client.post("/api/topics", json={"title": "获取测试话题"})
        topic_id = create_resp.json()["id"]
        resp = client.get(f"/api/topics/{topic_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == topic_id
        assert resp.json()["title"] == "获取测试话题"

    def test_get_topic_not_found(self):
        resp = client.get("/api/topics/nonexistent-id")
        assert resp.status_code == 404

    def test_delete_topic(self):
        create_resp = client.post("/api/topics", json={"title": "待删除话题"})
        topic_id = create_resp.json()["id"]
        resp = client.delete(f"/api/topics/{topic_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        # Verify gone
        get_resp = client.get(f"/api/topics/{topic_id}")
        assert get_resp.status_code == 404


class TestScoringAPI:
    @pytest.fixture(autouse=True)
    def setup_topic(self):
        resp = client.post("/api/topics", json={
            "title": TOPIC_AI[0],
            "raw_content": TOPIC_AI[1],
        })
        self.topic_id = resp.json()["id"]

    def test_score_with_default_weights(self):
        resp = client.post(f"/api/topics/{self.topic_id}/score", json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "score" in data
        score = data["score"]
        assert score["grade"] in ("S", "A", "B", "C")
        assert score["total_score"] > 0
        assert score["weight_mode"] == "new_account"
        assert score["platform"] == "wechat"

    def test_score_with_old_account_wechat(self):
        resp = client.post(f"/api/topics/{self.topic_id}/score", json={
            "weight_mode": "old_account",
            "platform": "wechat",
        })
        assert resp.status_code == 200
        score = resp.json()["score"]
        assert score["weight_mode"] == "old_account"
        assert score["platform"] == "wechat"

    def test_score_with_new_account_toutiao(self):
        resp = client.post(f"/api/topics/{self.topic_id}/score", json={
            "weight_mode": "new_account",
            "platform": "toutiao",
        })
        assert resp.status_code == 200
        score = resp.json()["score"]
        assert score["weight_mode"] == "new_account"
        assert score["platform"] == "toutiao"

    def test_score_all_six_combos(self):
        """Score the same topic with all 6 weight×platform combos."""
        results = {}
        for mode in ("new_account", "old_account"):
            for plat in ("wechat", "toutiao", "xiaohongshu"):
                resp = client.post(f"/api/topics/{self.topic_id}/score", json={
                    "weight_mode": mode, "platform": plat,
                })
                assert resp.status_code == 200, f"Failed for {mode}/{plat}: {resp.text}"
                score = resp.json()["score"]
                results[f"{mode}/{plat}"] = score["total_score"]
        # All should be within valid range
        for k, v in results.items():
            assert 0 <= v <= 100, f"{k}: {v} out of range"
        # Print for review
        print(f"\n  6 combo scores for AI topic: {json.dumps(results, indent=2)}")

    def test_re_scoring_updates_result(self):
        # Score with mode A
        resp_a = client.post(f"/api/topics/{self.topic_id}/score", json={
            "weight_mode": "new_account", "platform": "wechat",
        })
        score_a = resp_a.json()["score"]["total_score"]
        # Re-score with mode B
        resp_b = client.post(f"/api/topics/{self.topic_id}/score", json={
            "weight_mode": "old_account", "platform": "toutiao",
        })
        score_b = resp_b.json()["score"]["total_score"]
        assert score_a != score_b, f"Re-scoring should update score: {score_a} vs {score_b}"

    def test_score_nonexistent_topic(self):
        resp = client.post("/api/topics/fake-id/score", json={})
        assert resp.status_code == 404


class TestMatchingAPI:
    @pytest.fixture(autouse=True)
    def setup_topic(self):
        resp = client.post("/api/topics", json={
            "title": TOPIC_AI[0],
            "raw_content": TOPIC_AI[1],
        })
        self.topic_id = resp.json()["id"]
        # Score first (matching may use score data)
        client.post(f"/api/topics/{self.topic_id}/score", json={})

    def test_match_rule_based(self):
        resp = client.post(f"/api/topics/{self.topic_id}/match", json={
            "use_llm": False,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "matches" in data
        matches = data["matches"]
        assert 1 <= len(matches) <= 3, f"Should return 1-3 matches, got {len(matches)}"
        for m in matches:
            assert "celebrity_id" in m
            assert "celebrity_name" in m
            assert "match_score" in m
            assert "match_reason" in m
            assert "rank" in m

    @pytest.mark.slow
    def test_match_with_llm(self):
        resp = client.post(f"/api/topics/{self.topic_id}/match", json={
            "use_llm": True,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        matches = data["matches"]
        assert len(matches) >= 1
        # LLM match reasons should be more detailed
        for m in matches:
            assert len(m["match_reason"]) > 0

    def test_match_nonexistent_topic(self):
        resp = client.post("/api/topics/fake-id/match", json={"use_llm": False})
        assert resp.status_code == 404


class TestPipelineAPI:
    def test_pipeline_full_flow(self):
        resp = client.post("/api/pipeline/run", json={
            "title": TOPIC_AI[0],
            "raw_content": TOPIC_AI[1],
            "weight_mode": "new_account",
            "platform": "wechat",
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "topic_id" in data
        assert "score" in data
        assert "matches" in data
        assert data["score"]["grade"] in ("S", "A")
        assert len(data["matches"]) >= 1

    def test_pipeline_different_weights(self):
        r1 = client.post("/api/pipeline/run", json={
            "title": TOPIC_TESLA[0],
            "raw_content": TOPIC_TESLA[1],
            "weight_mode": "new_account",
            "platform": "toutiao",
        })
        r2 = client.post("/api/pipeline/run", json={
            "title": TOPIC_TESLA[0],
            "raw_content": TOPIC_TESLA[1],
            "weight_mode": "old_account",
            "platform": "toutiao",
        })
        s1 = r1.json()["score"]["total_score"]
        s2 = r2.json()["score"]["total_score"]
        assert s1 != s2, f"Different weight modes should differ: {s1} vs {s2}"

    def test_pipeline_gossip_low_score(self):
        resp = client.post("/api/pipeline/run", json={
            "title": TOPIC_GOSSIP[0],
            "raw_content": TOPIC_GOSSIP[1],
            "weight_mode": "new_account",
            "platform": "wechat",
        })
        assert resp.status_code == 200
        score = resp.json()["score"]
        assert score["grade"] == "C", f"Gossip should be C, got {score['grade']}/{score['total_score']}"


class TestReviewAPI:
    @pytest.fixture(autouse=True)
    def setup_topic(self):
        resp = client.post("/api/pipeline/run", json={
            "title": TOPIC_AI[0],
            "raw_content": TOPIC_AI[1],
        })
        self.topic_id = resp.json()["topic_id"]

    def test_confirm_topic(self):
        resp = client.post(f"/api/topics/{self.topic_id}/review", json={
            "action": "confirm",
            "note": "确认此选题",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"
        assert resp.json()["action"] == "confirm"

    def test_discard_topic(self):
        # Create a new topic to discard
        create_resp = client.post("/api/topics", json={"title": "要淘汰的话题"})
        tid = create_resp.json()["id"]
        # Score + match first
        client.post(f"/api/topics/{tid}/score", json={})
        client.post(f"/api/topics/{tid}/match", json={"use_llm": False})

        resp = client.post(f"/api/topics/{tid}/review", json={
            "action": "discard",
            "note": "内容质量不足",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "discarded"

    def test_backup_topic(self):
        create_resp = client.post("/api/topics", json={"title": "待暂存话题"})
        tid = create_resp.json()["id"]
        client.post(f"/api/topics/{tid}/score", json={})

        resp = client.post(f"/api/topics/{tid}/review", json={
            "action": "backup",
            "note": "暂时不确认，备用",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "backup"

    def test_adjust_celebrities(self):
        resp = client.post(f"/api/topics/{self.topic_id}/review", json={
            "action": "adjust",
            "note": "手动调整匹配",
            "adjust_celebrities": [
                {"celebrity_id": "custom_1", "celebrity_name": "自定义名人A", "match_score": 90},
                {"celebrity_id": "custom_2", "celebrity_name": "自定义名人B", "match_score": 85},
            ],
        })
        assert resp.status_code == 200
        # Verify match results updated
        get_resp = client.get(f"/api/topics/{self.topic_id}")
        matches = get_resp.json()["matches"]
        names = [m["celebrity_name"] for m in matches]
        assert "自定义名人A" in names
        assert "自定义名人B" in names

    def test_review_logs_present(self):
        client.post(f"/api/topics/{self.topic_id}/review", json={
            "action": "confirm", "note": "测试审核",
        })
        get_resp = client.get(f"/api/topics/{self.topic_id}")
        logs = get_resp.json().get("review_logs", [])
        assert len(logs) >= 1, f"Should have review logs, got {len(logs)}"
        assert logs[0]["action"] in ("confirm",)

    def test_status_flow_completeness(self):
        """Test full status flow: pending → scored → matched → confirmed."""
        # Create and score
        create_resp = client.post("/api/topics", json={"title": "完整流转测试"})
        tid = create_resp.json()["id"]
        assert create_resp.json()["status"] == "pending"

        # Score
        score_resp = client.post(f"/api/topics/{tid}/score", json={})
        assert score_resp.status_code == 200

        get1 = client.get(f"/api/topics/{tid}")
        assert get1.json()["status"] == "scored"

        # Match
        match_resp = client.post(f"/api/topics/{tid}/match", json={"use_llm": False})
        assert match_resp.status_code == 200

        get2 = client.get(f"/api/topics/{tid}")
        assert get2.json()["status"] == "matched"

        # Confirm
        review_resp = client.post(f"/api/topics/{tid}/review", json={
            "action": "confirm", "note": "确认选题",
        })
        assert review_resp.status_code == 200

        get3 = client.get(f"/api/topics/{tid}")
        assert get3.json()["status"] == "confirmed"

    def test_review_nonexistent_topic(self):
        resp = client.post("/api/topics/fake-id/review", json={"action": "confirm"})
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# 7. Edge cases & stress tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_create_topic_empty_title_should_fail_or_work(self):
        """FastAPI will validate; empty string is technically valid."""
        resp = client.post("/api/topics", json={"title": ""})
        # Either 200 (accepts empty) or 422 (validation error) — both OK
        assert resp.status_code in (200, 422), f"Unexpected status: {resp.status_code}"

    def test_create_topic_very_long_content(self):
        long_content = "这是一个很长的内容。" * 500  # ~5000 chars
        resp = client.post("/api/topics", json={
            "title": "长内容测试",
            "raw_content": long_content,
        })
        assert resp.status_code == 200

    def test_create_topic_unicode_special_chars(self):
        resp = client.post("/api/topics", json={
            "title": "🎉✨ AI话题 — 「深度」解读／分析 & 预测",
            "raw_content": "包含特殊字符：①②③，emoji 🚀，数学符号 ∑∏∫，HTML <div>test</div>",
        })
        assert resp.status_code == 200

    def test_list_topics_pagination(self):
        # Create multiple topics
        for i in range(5):
            client.post("/api/topics", json={"title": f"批量测试话题 #{i}"})
        resp = client.get("/api/topics?limit=2&offset=0")
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    def test_list_topics_filter_by_grade(self):
        resp = client.get("/api/topics?grade=S")
        assert resp.status_code == 200

    def test_list_topics_filter_by_min_score(self):
        resp = client.get("/api/topics?min_score=80")
        assert resp.status_code == 200

    def test_score_topic_with_unicode_in_title(self):
        create_resp = client.post("/api/topics", json={
            "title": "🎉 AI 大模型 — 「全模态」时代来临",
        })
        tid = create_resp.json()["id"]
        resp = client.post(f"/api/topics/{tid}/score", json={})
        assert resp.status_code == 200
        assert resp.json()["score"]["total_score"] > 0

    def test_rapid_sequential_scoring(self):
        """Score the same topic 3 times rapidly with different params."""
        create_resp = client.post("/api/topics", json={"title": "快速打分测试"})
        tid = create_resp.json()["id"]
        for i in range(3):
            resp = client.post(f"/api/topics/{tid}/score", json={
                "weight_mode": "new_account", "platform": "wechat",
            })
            assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# 8. Configuration & helpers
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_weights():
    """Reset weights to default after each test that might change them."""
    yield
    client.put("/api/config/weights", json={
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
    })


# ── Pytest config ────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests as slow (LLM calls)")

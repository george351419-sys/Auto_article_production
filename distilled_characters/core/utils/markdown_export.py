"""Render a distillation record into a human-readable Markdown report."""
from __future__ import annotations

from typing import Any


def _esc(text: Any) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    return s


def _bullets(items: list[Any], formatter=None) -> str:
    if not items:
        return ""
    fmt = formatter or (lambda x: _esc(x))
    return "\n".join(f"- {fmt(x)}" for x in items if x not in (None, "", {}))


def _render_expression_dna(d: dict) -> str:
    parts: list[str] = ["## 一、表达 DNA"]
    if d.get("language_tone"):
        parts.append(f"**语言调性**：{_esc(d['language_tone'])}")
    if d.get("sentence_rhythm"):
        parts.append(f"**句式节奏**：{_esc(d['sentence_rhythm'])}")
    if d.get("argumentation_style"):
        parts.append(f"**论证风格**：{_esc(d['argumentation_style'])}")

    habits = d.get("rhetorical_habits") or []
    if habits:
        parts.append("### 修辞习惯")
        for h in habits:
            if isinstance(h, str):
                parts.append(f"- {_esc(h)}")
                continue
            line = f"- **{_esc(h.get('pattern', '未命名'))}**"
            if h.get("description"):
                line += f"：{_esc(h['description'])}"
            parts.append(line)
            for ex in h.get("examples") or []:
                parts.append(f"  - 示例：「{_esc(ex)}」")

    phrases = d.get("catchphrases") or []
    if phrases:
        parts.append("### 口头禅 / 高频短语")
        for p in phrases:
            if isinstance(p, str):
                parts.append(f"- 「{_esc(p)}」")
                continue
            line = f"- 「{_esc(p.get('phrase', ''))}」"
            if p.get("frequency"):
                line += f"（×{p['frequency']}）"
            if p.get("context"):
                line += f" — {_esc(p['context'])}"
            parts.append(line)

    words = d.get("high_frequency_vocabulary") or d.get("high_freq_words") or []
    if words:
        parts.append("### 高频词汇")
        formatted = []
        for w in words:
            if isinstance(w, str):
                formatted.append(w)
            else:
                token = _esc(w.get("word", ""))
                if w.get("count"):
                    token += f"（×{w['count']}）"
                formatted.append(token)
        parts.append("、".join(formatted))
    return "\n\n".join(parts)


def _render_thinking_tools(d: dict) -> str:
    parts: list[str] = ["## 二、思维工具"]

    frameworks = d.get("analysis_frameworks") or []
    if frameworks:
        parts.append("### 分析框架")
        for f in frameworks:
            parts.append(f"#### {_esc(f.get('name', '未命名框架'))}")
            if f.get("description"):
                parts.append(_esc(f["description"]))
            dims = f.get("dimensions") or []
            if dims:
                parts.append("**维度**：" + " · ".join(_esc(x) for x in dims))
            scenarios = f.get("usage_scenarios") or []
            if scenarios:
                parts.append("**适用场景**：" + " · ".join(_esc(x) for x in scenarios))

    attr = d.get("attribution_logic") or {}
    if any(attr.get(k) for k in ("direction", "layers", "time_perspective")):
        parts.append("### 归因逻辑")
        if attr.get("direction"):
            parts.append(f"- 方向：{_esc(attr['direction'])}")
        if attr.get("layers"):
            parts.append(f"- 层次：{_esc(attr['layers'])}")
        if attr.get("time_perspective"):
            parts.append(f"- 时间视角：{_esc(attr['time_perspective'])}")

    paradigms = d.get("reasoning_paradigms") or []
    if paradigms:
        parts.append("### 推理范式")
        parts.append(_bullets(paradigms))

    theories = d.get("common_theories") or []
    if theories:
        parts.append("### 常用理论 / 概念")
        parts.append(_bullets(theories))
    return "\n\n".join(parts)


def _render_decision_rules(d: dict) -> str:
    parts: list[str] = ["## 三、决策规则"]

    priority = d.get("priority_rules") or []
    if priority:
        parts.append("### 优先级规则")
        for r in priority:
            if isinstance(r, str):
                parts.append(f"- {_esc(r)}")
                continue
            line = f"- **{_esc(r.get('rule', ''))}**"
            if r.get("explanation"):
                line += f"：{_esc(r['explanation'])}"
            parts.append(line)

    tradeoffs = d.get("tradeoff_principles") or []
    if tradeoffs:
        parts.append("### 取舍原则")
        for t in tradeoffs:
            if isinstance(t, str):
                parts.append(f"- {_esc(t)}")
                continue
            line = f"- {_esc(t.get('principle', ''))}"
            if t.get("explanation"):
                line += f" — {_esc(t['explanation'])}"
            parts.append(line)

    if d.get("risk_tolerance"):
        parts.append(f"**风险容忍度**：{_esc(d['risk_tolerance'])}")

    thresholds = d.get("evaluation_thresholds") or []
    if thresholds:
        parts.append("### 评估阈值")
        for t in thresholds:
            if isinstance(t, str):
                parts.append(f"- {_esc(t)}")
                continue
            criterion = _esc(t.get("criterion") or t.get("threshold") or "")
            line = f"- **{criterion}**"
            if t.get("context"):
                line += f"：{_esc(t['context'])}"
            parts.append(line)

    heuristics = d.get("heuristics") or []
    if heuristics:
        parts.append("### 决策启发式")
        for h in heuristics:
            if isinstance(h, str):
                parts.append(f"- {_esc(h)}")
                continue
            parts.append(f"#### {_esc(h.get('name', '未命名'))}")
            if h.get("description"):
                parts.append(_esc(h["description"]))
            if h.get("when_to_use"):
                parts.append(f"- ✅ 适用：{_esc(h['when_to_use'])}")
            if h.get("when_it_fails"):
                parts.append(f"- ⚠️ 失效：{_esc(h['when_it_fails'])}")
    return "\n\n".join(parts)


def _render_worldview(d: dict) -> str:
    parts: list[str] = ["## 四、世界观"]
    if d.get("attention_focus"):
        parts.append(f"**注意力焦点**：{_esc(d['attention_focus'])}")

    assumptions = d.get("fundamental_assumptions") or {}
    if any(assumptions.values()):
        parts.append("### 底层假设")
        if assumptions.get("human_nature"):
            parts.append(f"- 人性：{_esc(assumptions['human_nature'])}")
        if assumptions.get("world_nature"):
            parts.append(f"- 世界：{_esc(assumptions['world_nature'])}")
        if assumptions.get("time_orientation"):
            parts.append(f"- 时间观：{_esc(assumptions['time_orientation'])}")

    values = d.get("value_hierarchy") or []
    if values:
        parts.append("### 价值排序")
        for i, v in enumerate(values, 1):
            parts.append(f"{i}. {_esc(v)}")

    if d.get("unique_perspective"):
        parts.append(f"**独特视角**：{_esc(d['unique_perspective'])}")

    blindspots = d.get("cognitive_blind_spots") or []
    if blindspots:
        parts.append("### 认知盲区")
        parts.append(_bullets(blindspots))
    return "\n\n".join(parts)


def _render_boundaries(d: dict) -> str:
    parts: list[str] = ["## 五、边界与演化"]

    anti = d.get("anti_patterns") or []
    if anti:
        parts.append("### 反模式")
        for a in anti:
            if isinstance(a, str):
                parts.append(f"- {_esc(a)}")
                continue
            line = f"- **{_esc(a.get('pattern', ''))}**"
            if a.get("explanation"):
                line += f"：{_esc(a['explanation'])}"
            parts.append(line)

    red = d.get("value_red_lines") or []
    if red:
        parts.append("### 价值观底线")
        parts.append(_bullets(red))

    cap = d.get("capability_boundaries") or []
    if cap:
        parts.append("### 能力边界")
        parts.append(_bullets(cap))

    taboos = d.get("expression_taboos") or []
    if taboos:
        parts.append("### 表达禁忌")
        parts.append(_bullets(taboos))

    evolution = d.get("cognitive_evolution") or []
    if evolution:
        parts.append("### 认知演化")
        for p in evolution:
            if isinstance(p, str):
                parts.append(f"- {_esc(p)}")
                continue
            header = _esc(p.get("phase", ""))
            if p.get("time_period"):
                header = f"{p['time_period']} · {header}"
            parts.append(f"#### {header}")
            views = p.get("key_views") or []
            if views:
                parts.append("**核心观点**：" + " · ".join(_esc(v) for v in views))
            triggers = p.get("trigger_events") or []
            if triggers:
                parts.append("**触发事件**：" + "、".join(_esc(t) for t in triggers))
    return "\n\n".join(parts)


def _render_suggested_topics(items: list) -> str:
    if not items:
        return ""
    parts: list[str] = ["## 六、选题方向"]
    sorted_items = sorted(items, key=lambda x: -(x.get("confidence", 0) if isinstance(x, dict) else 0))
    for t in sorted_items:
        if isinstance(t, str):
            parts.append(f"- {_esc(t)}")
            continue
        conf = t.get("confidence", 0)
        line = f"### {_esc(t.get('topic', '未命名'))}（置信度 {round(conf * 100)}%）"
        parts.append(line)
        if t.get("description"):
            parts.append(_esc(t["description"]))
        if t.get("rationale"):
            parts.append(f"**依据**：{_esc(t['rationale'])}")
        keywords = t.get("keywords") or []
        if keywords:
            parts.append("**关键词**：" + "、".join(_esc(k) for k in keywords))
    return "\n\n".join(parts)


def _render_verification(v: dict) -> str:
    if not v:
        return ""
    parts: list[str] = ["## 验证报告"]
    cc = v.get("cross_consistency") or {}
    bt = v.get("back_testing") or {}
    bc = v.get("boundary_compliance") or {}

    parts.append(
        f"- **交叉一致性**：{'✅ 通过' if cc.get('passed') else '❌ 未通过'}"
        f"（覆盖率 {round((cc.get('coverage_rate') or 0) * 100)}%）"
    )
    for issue in cc.get("issues") or []:
        parts.append(f"  - {_esc(issue)}")
    parts.append(
        f"- **已知回测**：{'✅ 通过' if bt.get('passed') else '❌ 未通过'}"
        f"（匹配率 {round((bt.get('match_rate') or 0) * 100)}%）"
    )
    for issue in bt.get("issues") or []:
        parts.append(f"  - {_esc(issue)}")
    parts.append(
        f"- **边界合规**：{'✅ 通过' if bc.get('passed') else '❌ 未通过'}"
    )
    for issue in bc.get("issues") or []:
        parts.append(f"  - {_esc(issue)}")
    return "\n".join(parts)


def render_distillation_markdown(record: dict, character_name: str = "") -> str:
    """Render a distillation record into a Markdown report."""
    name = character_name or record.get("character_name") or "未命名人物"
    created = record.get("created_at", "")
    completed = record.get("completed_at", "")
    version = record.get("version", 1)
    status = record.get("status", "")

    header_lines = [
        f"# {name} · 人物思维蒸馏报告",
        "",
        f"- 蒸馏 ID：`{record.get('id', '')}`",
        f"- 版本：v{version}",
        f"- 状态：{status}",
    ]
    if created:
        header_lines.append(f"- 创建时间：{created}")
    if completed:
        header_lines.append(f"- 完成时间：{completed}")

    success_rate = (record.get("step_results") or {}).get("_step_success_rate")
    if success_rate is not None:
        header_lines.append(f"- 步骤成功率：{round(float(success_rate) * 100)}%")

    layers = record.get("layers") or {}
    sections = [
        "\n".join(header_lines),
        _render_expression_dna(layers.get("expression_dna") or {}),
        _render_thinking_tools(layers.get("thinking_tools") or {}),
        _render_decision_rules(layers.get("decision_rules") or {}),
        _render_worldview(layers.get("worldview") or {}),
        _render_boundaries(layers.get("boundaries_evolution") or {}),
        _render_suggested_topics(layers.get("suggested_topics") or []),
        _render_verification(record.get("verification") or {}),
    ]
    return "\n\n".join(s for s in sections if s).rstrip() + "\n"

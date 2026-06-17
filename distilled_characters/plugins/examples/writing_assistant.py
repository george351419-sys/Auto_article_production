"""Example: Writing Assistant Plugin.

Consumes a distillation result and helps with:
- Generating article outlines in the character's voice
- Writing content mimicking the character's style
- Getting critique from the character's perspective
"""
from __future__ import annotations

from typing import Any

from plugins import DistillationPlugin, PluginCapability


class WritingAssistant(DistillationPlugin):
    name = "writing_assistant"
    description = "基于蒸馏结果辅助写作：生成提纲、模仿文风写作、角色视角评审"

    def get_capabilities(self) -> list[PluginCapability]:
        return [
            PluginCapability(
                name="generate_outline",
                description="根据给定话题，以该人物的思维框架生成文章提纲",
                input_schema={"topic": "string", "distillation_result": "dict (layers)"},
                output_schema={"outline": "list of sections"},
            ),
            PluginCapability(
                name="write_section",
                description="以人物的文风和论证方式撰写指定段落",
                input_schema={"topic": "string", "outline_item": "string", "expression_dna": "dict"},
                output_schema={"content": "string"},
            ),
            PluginCapability(
                name="critique",
                description="以该人物的视角和标准评审一段文字",
                input_schema={"text": "string", "decision_rules": "dict", "worldview": "dict"},
                output_schema={"critique": "string", "score": "int"},
            ),
        ]

    async def execute(
        self,
        capability: str,
        input_data: dict[str, Any],
        llm: Any,
    ) -> dict[str, Any]:
        dist = input_data.get("distillation_result", {})
        layers = dist.get("layers", {})
        expression_dna = layers.get("expression_dna", {})
        thinking_tools = layers.get("thinking_tools", {})
        decision_rules = layers.get("decision_rules", {})
        worldview = layers.get("worldview", {})

        if capability == "generate_outline":
            topic = input_data.get("topic", "")
            tone = expression_dna.get("language_tone", "")
            frameworks = thinking_tools.get("analysis_frameworks", [])
            attention = worldview.get("attention_focus", "")

            prompt = f"""你正在以一位具有以下思维特征的人物身份思考：
- 语言调性: {tone}
- 分析框架: {frameworks}
- 注意力焦点: {attention}

请为话题「{topic}」生成一份文章提纲，使用该人物习惯的分析结构。
输出应为JSON格式：{{"title": "...", "sections": [{{"heading": "...", "key_points": [...]}}]}}"""

            raw = await llm.send_prompt(prompt)
            import json
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"title": topic, "sections": [{"heading": raw[:100], "key_points": []}]}

        elif capability == "write_section":
            topic = input_data.get("topic", "")
            outline_item = input_data.get("outline_item", "")
            tone = expression_dna.get("language_tone", "")
            rhythm = expression_dna.get("sentence_rhythm", "")
            catchphrases = expression_dna.get("catchphrases", [])

            prompt = f"""以以下文风写作：
- 语言调性: {tone}
- 句式节奏: {rhythm}
- 惯用语: {[c.get('phrase', '') for c in catchphrases]}

话题: {topic}
要写的段落: {outline_item}

请用该人物的口吻和论证风格撰写此段落（500-800字）。"""

            raw = await llm.send_prompt(prompt)
            return {"content": raw}

        elif capability == "critique":
            text = input_data.get("text", "")
            value_hierarchy = worldview.get("value_hierarchy", [])
            anti_patterns = layers.get("boundaries_evolution", {}).get("anti_patterns", [])
            thresholds = decision_rules.get("evaluation_thresholds", [])

            prompt = f"""你以一位具有以下标准的人物身份来评审文字：
- 价值排序: {value_hierarchy}
- 反对的思维模式: {anti_patterns}
- 评价标准: {thresholds}

请对以下文字进行评审，以该人物的语气给出批评和建议。
输出JSON格式：{{"critique": "...", "score": 1-10, "strengths": [...], "weaknesses": [...]}}

待评审文字：
{text[:3000]}"""

            raw = await llm.send_prompt(prompt)
            import json
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"critique": raw, "score": 5, "strengths": [], "weaknesses": []}

        return {"error": f"Unknown capability: {capability}"}

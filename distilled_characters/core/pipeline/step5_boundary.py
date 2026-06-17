"""Step 5: Boundary completion — anti-patterns and cognitive evolution."""
from __future__ import annotations

import json
from typing import Any

from core.llm.base import AbstractLLMBackend
from core.pipeline.base import BaseDistillationStep
from core.prompts.builder import build_step5_prompt


class Step5Boundary(BaseDistillationStep):
    name = "step5_boundary"
    label = "边界补全：反模式与认知演化"
    description = "识别反模式、价值观底线、能力边界、表达禁忌、认知演化路径"

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        character_name = context.get("character_name", "未知人物")

        def _get(key, subkey, default):
            step = context.get(key, {})
            return step.get("data", {}).get(subkey, default) if isinstance(step, dict) else default

        triples = _get("step2_surface", "triples", [])
        thinking_tools = _get("step3_midlayer", "thinking_tools", {})
        decision_rules = _get("step3_midlayer", "decision_rules", {})
        worldview = _get("step4_deep", "worldview", {})

        # Fallback: if no triples from step2, use raw materials
        if not triples:
            materials = context.get("materials", [])
            triples = [
                {"material_id": m.get("id", ""), "source": m.get("title", ""),
                 "content": m.get("raw_content", "")[:3000]}
                for m in materials[:10]
            ]

        return build_step5_prompt(
            character_name, triples, thinking_tools, decision_rules, worldview
        )

    def parse_response(self, llm_output: str) -> dict[str, Any]:
        text = self._extract_json(llm_output)
        data = self._safe_json_parse(text)
        return {
            "boundaries_evolution": data.get("boundaries_evolution", {}),
        }

"""Step 7: Topics recommendation — suggest suitable topics for the character."""
from __future__ import annotations

import json
from typing import Any

from core.llm.base import AbstractLLMBackend
from core.pipeline.base import BaseDistillationStep
from core.prompts.builder import build_topics_prompt


class Step7Topics(BaseDistillationStep):
    name = "step7_topics"
    label = "话题推荐：人物适合的选题方向"
    description = "基于五层蒸馏结果，推荐人物适合讨论的话题，含置信度评分"

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        character_name = context.get("character_name", "未知人物")
        triples = self._get_triples(context)
        layers_summary = self._get_layers_summary(context)
        return build_topics_prompt(character_name, triples, layers_summary)

    def _get_triples(self, context: dict[str, Any]) -> list[dict]:
        step2 = context.get("step2_surface", {})
        triples = step2.get("data", {}).get("triples", []) if isinstance(step2, dict) else []
        if triples:
            return triples
        materials = context.get("materials", [])
        return [
            {"material_id": m.get("id", ""), "source": m.get("title", ""),
             "content": m.get("raw_content", "")[:2000]}
            for m in materials[:15]
        ]

    def _get_layers_summary(self, context: dict[str, Any]) -> dict:
        """Build a summary of all 5 layers for the LLM to work with."""
        def _data(step_key: str, subkey: str) -> dict:
            step = context.get(step_key, {})
            return step.get("data", {}).get(subkey, {}) if isinstance(step, dict) else {}

        return {
            "expression_dna": _data("step2_surface", "expression_dna_draft"),
            "thinking_tools": _data("step3_midlayer", "thinking_tools"),
            "decision_rules": _data("step3_midlayer", "decision_rules"),
            "worldview": _data("step4_deep", "worldview"),
            "boundaries_evolution": _data("step5_boundary", "boundaries_evolution"),
        }

    def parse_response(self, llm_output: str) -> dict[str, Any]:
        text = self._extract_json(llm_output)
        data = self._safe_json_parse(text)
        return {
            "suggested_topics": data.get("suggested_topics", []),
        }

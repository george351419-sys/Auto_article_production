"""Step 4: Deep distillation — unique perspective and worldview."""
from __future__ import annotations

import json
from typing import Any

from core.llm.base import AbstractLLMBackend
from core.pipeline.base import BaseDistillationStep
from core.prompts.builder import build_step4_prompt


class Step4Deep(BaseDistillationStep):
    name = "step4_deep"
    label = "深层蒸馏：独特视角与世界观"
    description = "挖掘注意力焦点、底层假设、价值排序、认知盲区等世界观核心要素"

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        character_name = context.get("character_name", "未知人物")

        def _get(key, subkey, default):
            step = context.get(key, {})
            return step.get("data", {}).get(subkey, default) if isinstance(step, dict) else default

        triples = _get("step2_surface", "triples", [])
        thinking_tools = _get("step3_midlayer", "thinking_tools", {})
        decision_rules = _get("step3_midlayer", "decision_rules", {})

        # Fallback: if no triples from step2, use raw materials
        if not triples:
            materials = context.get("materials", [])
            triples = [
                {"material_id": m.get("id", ""), "source": m.get("title", ""),
                 "content": m.get("raw_content", "")[:3000]}
                for m in materials[:15]
            ]

        return build_step4_prompt(character_name, triples, thinking_tools, decision_rules)

    def parse_response(self, llm_output: str) -> dict[str, Any]:
        text = self._extract_json(llm_output)
        data = self._safe_json_parse(text)
        return {
            "worldview": data.get("worldview", {}),
        }

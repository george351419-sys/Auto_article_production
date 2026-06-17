"""Step 3: Mid-layer distillation — thinking models and decision rules."""
from __future__ import annotations

import json
from typing import Any

from core.llm.base import AbstractLLMBackend
from core.pipeline.base import BaseDistillationStep
from core.prompts.builder import build_step3_prompt


class Step3MidLayer(BaseDistillationStep):
    name = "step3_midlayer"
    label = "中层蒸馏：思维模型与决策规则"
    description = "萃取分析框架、归因逻辑、推理范式、决策启发式、评估阈值"

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        character_name = context.get("character_name", "未知人物")
        triples = self._get_triples(context)
        return build_step3_prompt(character_name, triples)

    def _get_triples(self, context: dict[str, Any]) -> list[dict]:
        step2 = context.get("step2_surface", {})
        triples = step2.get("data", {}).get("triples", []) if isinstance(step2, dict) else []
        if triples:
            return triples
        # Fallback: use raw materials directly
        materials = context.get("materials", [])
        return [
            {"material_id": m.get("id", ""), "source": m.get("title", ""),
             "content": m.get("raw_content", "")[:3000]}
            for m in materials[:20]
        ]

    def parse_response(self, llm_output: str) -> dict[str, Any]:
        text = self._extract_json(llm_output)
        data = self._safe_json_parse(text)
        return {
            "thinking_tools": data.get("thinking_tools", {}),
            "decision_rules": data.get("decision_rules", {}),
        }

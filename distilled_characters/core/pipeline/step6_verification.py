"""Step 6: Triple verification and structured packaging."""
from __future__ import annotations

import json
from typing import Any

from core.llm.base import AbstractLLMBackend
from core.pipeline.base import BaseDistillationStep
from core.prompts.builder import build_step6_prompt


class Step6Verification(BaseDistillationStep):
    name = "step6_verification"
    label = "三重验证与结构化封装"
    description = "交叉一致性验证、已知问题回测、边界合规校验，最终打包五层输出"

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        character_name = context.get("character_name", "未知人物")

        def _get(key, subkey, default):
            step = context.get(key, {})
            return step.get("data", {}).get(subkey, default) if isinstance(step, dict) else default

        all_layers = {
            "expression_dna": _get("step2_surface", "expression_dna_draft", {}),
            "thinking_tools": _get("step3_midlayer", "thinking_tools", {}),
            "decision_rules": _get("step3_midlayer", "decision_rules", {}),
            "worldview": _get("step4_deep", "worldview", {}),
            "boundaries_evolution": _get("step5_boundary", "boundaries_evolution", {}),
        }

        materials = context.get("materials", [])
        materials_summary_parts = []
        for m in materials[:10]:  # Limit to first 10
            materials_summary_parts.append(
                f"- [{m.get('source_type', 'unknown')}] {m.get('title', m.get('id', ''))}: "
                f"{m.get('cleaned_content', m.get('raw_content', ''))[:200]}..."
            )
        materials_summary = "\n".join(materials_summary_parts)

        return build_step6_prompt(character_name, all_layers, materials_summary)

    def parse_response(self, llm_output: str) -> dict[str, Any]:
        text = self._extract_json(llm_output)
        data = self._safe_json_parse(text)
        return {
            "verification": data.get("verification", {}),
            "layers": data.get("layers", {}),
        }

"""Step 2: Surface extraction — thought-chain triples and expression DNA.
When there are many materials, they are batched to avoid exceeding context limits.
"""
from __future__ import annotations

import json
from typing import Any

from core.llm.base import AbstractLLMBackend
from core.pipeline.base import BaseDistillationStep
from core.prompts.builder import build_step2_prompt


class Step2Surface(BaseDistillationStep):
    name = "step2_surface"
    label = "表层萃取：思维链三元组与表达DNA"
    description = "提取(问题→思考→结论)三元组，统计高频词汇、比喻、口头禅等表达特征"

    BATCH_SIZE = 15  # Process this many S/A-grade materials per LLM call

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        character_name = context.get("character_name", "未知人物")
        materials = self._get_enriched_materials(context)
        return build_step2_prompt(character_name, materials[:self.BATCH_SIZE])

    def _get_enriched_materials(self, context: dict[str, Any]) -> list[dict]:
        """Merge classification results into materials, or return raw materials as fallback."""
        materials = context.get("materials", [])
        step1 = context.get("step1_collection", {})
        if step1 and isinstance(step1, dict):
            classified = step1.get("data", {}).get("materials_classified", [])
            if classified:
                enriched = []
                for m in materials:
                    for c in classified:
                        if not isinstance(c, dict):
                            continue
                        if c.get("material_id") == m.get("id"):
                            m = {**m, "confidence": c.get("confidence", "B"),
                                 "cleaned_content": c.get("cleaned_content", m.get("raw_content", ""))}
                            break
                    enriched.append(m)
                return enriched
        return materials

    async def execute(
        self, llm: AbstractLLMBackend, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Batch-process materials, then merge triples."""
        character_name = context.get("character_name", "未知人物")
        materials = self._get_enriched_materials(context)

        # Filter to S/A grade if available, otherwise use first N materials
        filtered = [m for m in materials if m.get("confidence") in ("S", "A")]
        if not filtered:
            filtered = materials[:self.BATCH_SIZE]

        if not filtered:
            return {"triples": [], "expression_dna_draft": {}}

        all_triples = []
        all_dna = {}
        for batch_start in range(0, len(filtered), self.BATCH_SIZE):
            batch = filtered[batch_start:batch_start + self.BATCH_SIZE]
            system_msg, user_msg = build_step2_prompt(character_name, batch)
            try:
                raw = await llm.send_prompt(user_msg, system_message=system_msg)
                result = self.parse_response(raw)
                all_triples.extend(result.get("triples", []))
                # Keep the first expression_dna_draft as the primary
                if not all_dna and result.get("expression_dna_draft"):
                    all_dna = result["expression_dna_draft"]
            except Exception:
                continue  # Skip failed batches

        return {
            "triples": all_triples,
            "expression_dna_draft": all_dna,
        }

    def parse_response(self, llm_output: str) -> dict[str, Any]:
        text = self._extract_json(llm_output)
        data = self._safe_json_parse(text)
        return {
            "triples": data.get("triples", []),
            "expression_dna_draft": data.get("expression_dna_draft", {}),
        }

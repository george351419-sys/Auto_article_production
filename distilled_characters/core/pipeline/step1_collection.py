"""Step 1: Material ingestion, classification, and confidence grading.
When there are many materials, they are batched to avoid exceeding context limits.
"""
from __future__ import annotations

import json
from typing import Any

from core.llm.base import AbstractLLMBackend
from core.pipeline.base import BaseDistillationStep
from core.prompts.builder import build_step1_prompt


class Step1Collection(BaseDistillationStep):
    name = "step1_collection"
    label = "素材归档与置信度分级"
    description = "对原始素材按六大类型分类，标注S/A/B/C置信度，清洗噪音"

    BATCH_SIZE = 20  # Process this many materials per LLM call

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        character_name = context.get("character_name", "未知人物")
        materials = context.get("materials", [])
        # Only use first BATCH_SIZE for non-batch mode
        return build_step1_prompt(character_name, materials[:self.BATCH_SIZE])

    async def execute(
        self, llm: AbstractLLMBackend, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Batch-process all materials, then merge classifications."""
        character_name = context.get("character_name", "未知人物")
        materials = context.get("materials", [])

        if not materials:
            return {
                "materials_classified": [],
                "filtered_materials_ids": [],
                "noise_removed_ids": [],
            }

        all_classified = []
        for batch_start in range(0, len(materials), self.BATCH_SIZE):
            batch = materials[batch_start:batch_start + self.BATCH_SIZE]
            system_msg, user_msg = build_step1_prompt(character_name, batch)
            try:
                raw = await llm.send_prompt(user_msg, system_message=system_msg)
                classified = self.parse_response(raw)
                all_classified.extend(classified.get("materials_classified", []))
            except Exception:
                # If batch classification fails, mark materials with default classification
                for m in batch:
                    all_classified.append({
                        "material_id": m.get("id", ""),
                        "source_type": "fragment_expression",
                        "confidence": "B",
                        "cleaned_content": m.get("raw_content", "")[:2000],
                        "tags": [],
                        "rationale": "批次分类失败，回退为默认B级",
                    })

        filtered = [item.get("material_id") for item in all_classified
                    if isinstance(item, dict) and item.get("confidence") != "C"]
        noise = [item.get("material_id") for item in all_classified
                 if isinstance(item, dict) and item.get("confidence") == "C"]

        return {
            "materials_classified": all_classified,
            "filtered_materials_ids": filtered,
            "noise_removed_ids": noise,
        }

    def parse_response(self, llm_output: str) -> dict[str, Any]:
        text = self._extract_json(llm_output)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = []

        # Normalize to list
        if isinstance(data, dict):
            if "materials_classified" in data:
                data = data["materials_classified"]
            else:
                data = [data]

        if not isinstance(data, list):
            data = [data]

        filtered = []
        noise_ids = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("confidence") == "C":
                noise_ids.append(item.get("material_id", ""))
            else:
                filtered.append(item.get("material_id", ""))

        return {
            "materials_classified": data,
            "filtered_materials_ids": filtered,
            "noise_removed_ids": noise_ids,
        }

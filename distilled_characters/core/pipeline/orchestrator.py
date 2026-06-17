"""Pipeline orchestrator — chains the 6 steps together.

Supports:
- Full pipeline run (all 6 steps in sequence)
- Single step execution (for ad-hoc module reuse)
- Real-time progress reporting via callback
- Graceful degradation: when a step fails, pipeline feeds raw materials to downstream steps
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from core.llm.base import AbstractLLMBackend
from core.pipeline.base import BaseDistillationStep
from core.pipeline.step1_collection import Step1Collection
from core.pipeline.step2_surface import Step2Surface
from core.pipeline.step3_midlayer import Step3MidLayer
from core.pipeline.step4_deep import Step4Deep
from core.pipeline.step5_boundary import Step5Boundary
from core.pipeline.step6_verification import Step6Verification
from core.pipeline.step7_topics import Step7Topics

logger = logging.getLogger("pipeline.orchestrator")

DEFAULT_STEPS: list[BaseDistillationStep] = [
    Step1Collection(),
    Step2Surface(),
    Step3MidLayer(),
    Step4Deep(),
    Step5Boundary(),
    Step6Verification(),
    Step7Topics(),
]

ProgressCallback = Callable[[str, str, float], None]
# (step_name, status, progress_fraction)


class PipelineOrchestrator:
    def __init__(
        self,
        llm_backend: AbstractLLMBackend,
        steps: Optional[list[BaseDistillationStep]] = None,
    ) -> None:
        self.llm = llm_backend
        self.steps = steps or DEFAULT_STEPS
        self._progress_callback: Optional[ProgressCallback] = None

    def on_progress(self, callback: ProgressCallback) -> None:
        self._progress_callback = callback

    async def run_full(
        self,
        character_name: str,
        materials: list[dict],
    ) -> dict[str, Any]:
        """Run all 6 steps sequentially, building up context.

        On step failure, downstream steps receive raw material content
        so the pipeline never produces empty results.
        """
        context: dict[str, Any] = {
            "character_name": character_name,
            "materials": materials,
        }
        total_steps = len(self.steps)
        step_success_count = 0
        # Track the best available materials_text for downstream fallback
        materials_text_parts = []
        for i, m in enumerate(materials[:50]):  # cap at 50 for fallback text
            content = m.get("raw_content", "")[:3000]
            title = m.get("title", f"素材{i+1}")
            materials_text_parts.append(f"## {title}\n{content}\n")
        context["_materials_text"] = "\n".join(materials_text_parts)

        for i, step in enumerate(self.steps):
            progress = (i) / total_steps
            self._report_progress(step.name, "running", progress)

            try:
                result = await step.execute(self.llm, context)
                context[step.name] = {
                    "status": "completed",
                    "data": result,
                }
                step_success_count += 1
                self._report_progress(step.name, "completed", (i + 1) / total_steps)
            except Exception as e:
                # Store the error but inject fallback data so downstream steps can proceed
                logger.error("Step %s failed: %s", step.name, e)
                fallback_data = self._fallback_for_step(step.name, context)
                context[step.name] = {
                    "status": "failed",
                    "data": fallback_data,
                    "error": str(e),
                }
                self._report_progress(step.name, "failed", (i + 1) / total_steps)

        context["_step_success_rate"] = step_success_count / total_steps if total_steps else 0
        return self._build_result(context)

    def _fallback_for_step(self, step_name: str, context: dict) -> dict:
        """Generate fallback data when a step fails, so downstream steps get input."""
        materials = context.get("materials", [])
        materials_text = context.get("_materials_text", "")

        if step_name == "step1_collection":
            # Mark all materials as B-grade with truncated content
            classified = []
            for m in materials:
                classified.append({
                    "material_id": m.get("id", ""),
                    "source_type": m.get("source_type", "fragment_expression"),
                    "confidence": "B",
                    "cleaned_content": m.get("raw_content", "")[:2000],
                    "tags": [],
                    "rationale": "自动回退：步骤1执行失败，默认B级",
                })
            return {
                "materials_classified": classified,
                "filtered_materials_ids": [m.get("id") for m in materials],
                "noise_removed_ids": [],
            }

        if step_name == "step2_surface":
            return {"triples": [], "expression_dna_draft": {}}

        if step_name == "step3_midlayer":
            return {"thinking_tools": {}, "decision_rules": {}}

        if step_name == "step4_deep":
            return {"worldview": {}}

        if step_name == "step5_boundary":
            return {"boundaries_evolution": {}}

        if step_name == "step6_verification":
            return {"verification": {}, "layers": {}}

        if step_name == "step7_topics":
            return {"suggested_topics": []}

        return {}

    async def run_step(
        self,
        step_name: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a single step with custom context. This is the module-reuse entry point."""
        step = self._get_step(step_name)
        if step is None:
            raise ValueError(f"Unknown step: {step_name}. Available: {self._step_names()}")

        return await step.execute(self.llm, context)

    def _get_step(self, name: str) -> Optional[BaseDistillationStep]:
        for step in self.steps:
            if step.name == name:
                return step
        return None

    def _step_names(self) -> list[str]:
        return [s.name for s in self.steps]

    def _report_progress(self, step_name: str, status: str, progress: float) -> None:
        if self._progress_callback:
            self._progress_callback(step_name, status, progress)

    def _build_result(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract the final output from accumulated context."""
        step6 = context.get("step6_verification", {})
        step6_data = step6.get("data", {}) if isinstance(step6, dict) else {}

        layers = step6_data.get("layers", {})

        # If step6 didn't produce layers (e.g., failed), assemble from individual steps
        if not layers:
            layers = self._assemble_layers(context)

        verification = step6_data.get("verification", {})

        # Collect step results for storage
        step_results = {}
        for key, value in context.items():
            if key.startswith("step"):
                step_results[key] = value

        return {
            "layers": layers,
            "verification": verification,
            "step_results": step_results,
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
        }

    @staticmethod
    def _assemble_layers(context: dict[str, Any]) -> dict[str, Any]:
        """Assemble 5 layers from individual step results with fallback to empty but well-structured output."""
        def _data(key: str, subkey: str) -> dict:
            step = context.get(key, {})
            if isinstance(step, dict) and "data" in step:
                val = step["data"].get(subkey, {})
                return val if isinstance(val, (dict, list)) else {}
            return {}

        return {
            "expression_dna": _data("step2_surface", "expression_dna_draft"),
            "thinking_tools": _data("step3_midlayer", "thinking_tools"),
            "decision_rules": _data("step3_midlayer", "decision_rules"),
            "worldview": _data("step4_deep", "worldview"),
            "boundaries_evolution": _data("step5_boundary", "boundaries_evolution"),
            "suggested_topics": _data("step7_topics", "suggested_topics"),
        }


# ── Module registry ───────────────────────────────────────────────

def get_all_steps() -> list[BaseDistillationStep]:
    """Return all available distillation steps."""
    return DEFAULT_STEPS


def get_step_info() -> list[dict[str, str]]:
    """Return step metadata for the API / frontend."""
    return [
        {
            "name": s.name,
            "label": s.label,
            "description": s.description,
        }
        for s in DEFAULT_STEPS
    ]

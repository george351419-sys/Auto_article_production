"""Pipeline step input/output schemas."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PipelineStepResult(BaseModel):
    """Generic wrapper for the output of any pipeline step."""
    step_name: str
    status: str = "completed"  # pending | running | completed | failed
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class Step1Output(BaseModel):
    """Output from step1_collection: material classification and grading."""
    character_name: str = ""
    materials_classified: list[dict] = Field(default_factory=list)
    # Each dict: {material_id, source_type, confidence, cleaned_content, tags, rationale}
    filtered_materials_ids: list[str] = Field(default_factory=list)
    noise_removed_ids: list[str] = Field(default_factory=list)


class Step2Output(BaseModel):
    """Output from step2_surface: thought triples and expression DNA draft."""
    triples: list[dict] = Field(default_factory=list)
    # Each dict: {material_id, problem_scenario, thinking_path, conclusion, tags}
    expression_dna_draft: dict = Field(default_factory=dict)
    # {language_tone, sentence_rhythm, rhetorical_habits, catchphrases, high_freq_words}


class Step3Output(BaseModel):
    """Output from step3_midlayer: thinking tools and decision rules."""
    thinking_tools: dict = Field(default_factory=dict)
    decision_rules: dict = Field(default_factory=dict)


class Step4Output(BaseModel):
    """Output from step4_deep: worldview."""
    worldview: dict = Field(default_factory=dict)


class Step5Output(BaseModel):
    """Output from step5_boundary: anti-patterns and evolution."""
    boundaries_evolution: dict = Field(default_factory=dict)


class Step6Output(BaseModel):
    """Output from step6_verification: verification report + packaged result."""
    verification: dict = Field(default_factory=dict)
    layers: dict = Field(default_factory=dict)

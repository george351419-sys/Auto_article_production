"""
Pydantic models for the 5-layer distillation output structure.
This is the core deliverable schema — everything else revolves around it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Expression DNA Layer ──────────────────────────────────────────────

class RhetoricalHabit(BaseModel):
    pattern: str
    description: str
    examples: list[str] = Field(default_factory=list)


class Catchphrase(BaseModel):
    phrase: str
    frequency: int = 0
    context: str = ""


class HighFrequencyWord(BaseModel):
    word: str
    count: int = 0


class ExpressionDNA(BaseModel):
    language_tone: str = ""
    sentence_rhythm: str = ""
    rhetorical_habits: list[RhetoricalHabit] = Field(default_factory=list)
    catchphrases: list[Catchphrase] = Field(default_factory=list)
    high_frequency_vocabulary: list[HighFrequencyWord] = Field(default_factory=list)
    argumentation_style: str = ""


# ── Thinking Tools Layer ──────────────────────────────────────────────

class AnalysisFramework(BaseModel):
    name: str
    description: str
    dimensions: list[str] = Field(default_factory=list)
    usage_scenarios: list[str] = Field(default_factory=list)
    source_material_ids: list[str] = Field(default_factory=list)


class AttributionLogic(BaseModel):
    direction: str = ""  # "internal" | "external" | "mixed"
    layers: str = ""  # "single" | "multi"
    time_perspective: str = ""  # "short-term" | "long-term" | "historical"


class ThinkingTools(BaseModel):
    analysis_frameworks: list[AnalysisFramework] = Field(default_factory=list)
    attribution_logic: AttributionLogic = Field(default_factory=AttributionLogic())
    reasoning_paradigms: list[str] = Field(default_factory=list)
    common_theories: list[str] = Field(default_factory=list)


# ── Decision Rules Layer ──────────────────────────────────────────────

class PriorityRule(BaseModel):
    rule: str
    explanation: str = ""
    source_material_ids: list[str] = Field(default_factory=list)


class EvaluationThreshold(BaseModel):
    criterion: str
    threshold: str
    context: str = ""


class Heuristic(BaseModel):
    name: str
    description: str
    when_to_use: str = ""
    when_it_fails: str = ""


class DecisionRules(BaseModel):
    priority_rules: list[PriorityRule] = Field(default_factory=list)
    tradeoff_principles: list[str] = Field(default_factory=list)
    risk_tolerance: str = ""
    evaluation_thresholds: list[EvaluationThreshold] = Field(default_factory=list)
    heuristics: list[Heuristic] = Field(default_factory=list)


# ── Worldview Layer ───────────────────────────────────────────────────

class FundamentalAssumptions(BaseModel):
    human_nature: str = ""
    world_nature: str = ""
    time_orientation: str = ""


class Worldview(BaseModel):
    attention_focus: str = ""
    fundamental_assumptions: FundamentalAssumptions = Field(
        default_factory=FundamentalAssumptions
    )
    value_hierarchy: list[str] = Field(default_factory=list)
    unique_perspective: str = ""
    cognitive_blind_spots: list[str] = Field(default_factory=list)


# ── Boundaries & Evolution Layer ──────────────────────────────────────

class AntiPattern(BaseModel):
    pattern: str
    explanation: str = ""


class CognitivePhase(BaseModel):
    phase: str
    time_period: str = ""
    key_views: list[str] = Field(default_factory=list)
    trigger_events: list[str] = Field(default_factory=list)


class SuggestedTopic(BaseModel):
    topic: str
    description: str = ""
    confidence: float = 0.0
    rationale: str = ""
    keywords: list[str] = Field(default_factory=list)


class BoundariesEvolution(BaseModel):
    anti_patterns: list[AntiPattern] = Field(default_factory=list)
    value_red_lines: list[str] = Field(default_factory=list)
    capability_boundaries: list[str] = Field(default_factory=list)
    expression_taboos: list[str] = Field(default_factory=list)
    cognitive_evolution: list[CognitivePhase] = Field(default_factory=list)


# ── Five Layer Output (the core deliverable) ──────────────────────────

class FiveLayerOutput(BaseModel):
    expression_dna: ExpressionDNA = Field(default_factory=ExpressionDNA)
    thinking_tools: ThinkingTools = Field(default_factory=ThinkingTools)
    decision_rules: DecisionRules = Field(default_factory=DecisionRules)
    worldview: Worldview = Field(default_factory=Worldview)
    boundaries_evolution: BoundariesEvolution = Field(
        default_factory=BoundariesEvolution
    )
    suggested_topics: list[SuggestedTopic] = Field(default_factory=list)


# ── Verification ──────────────────────────────────────────────────────

class CrossConsistencyCheck(BaseModel):
    passed: bool = True
    issues: list[str] = Field(default_factory=list)
    coverage_rate: float = 0.0


class BackTestResult(BaseModel):
    passed: bool = True
    match_rate: float = 0.0
    test_cases: list[dict] = Field(default_factory=list)


class BoundaryComplianceCheck(BaseModel):
    passed: bool = True
    issues: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    cross_consistency: CrossConsistencyCheck = Field(
        default_factory=CrossConsistencyCheck
    )
    back_testing: BackTestResult = Field(default_factory=BackTestResult)
    boundary_compliance: BoundaryComplianceCheck = Field(
        default_factory=BoundaryComplianceCheck
    )


# ── Distillation Result (wraps everything) ────────────────────────────

class DistillationResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    character_id: str
    version: int = 1
    status: str = "pending"  # pending | in_progress | completed | failed
    pipeline_version: str = "1.0.0"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    layers: FiveLayerOutput = Field(default_factory=FiveLayerOutput)
    verification: Optional[VerificationReport] = None
    source_material_ids: list[str] = Field(default_factory=list)
    step_results: dict = Field(default_factory=dict)
    error_message: Optional[str] = None

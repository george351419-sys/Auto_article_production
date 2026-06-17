"""Pydantic models for the topic selection system."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Topic ───────────────────────────────────────────────────────────────

class SourceMaterial(BaseModel):
    url: str
    title: str = ""
    platform: str = ""


class TopicCreate(BaseModel):
    title: str
    source_url: str = ""
    source_type: str = "manual"
    source_platform: str = ""
    raw_content: str = ""
    heat_level: str = "normal"
    source_material: list[SourceMaterial] = []


class Topic(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    source_url: str = ""
    source_type: str = "manual"
    source_platform: str = ""
    raw_content: str = ""
    heat_level: str = "normal"
    status: str = "pending"
    source_material: str = "[]"
    batch_id: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ── Scoring ─────────────────────────────────────────────────────────────

class DimensionScores(BaseModel):
    relevance: float = 0.0    # 领域相关性
    timeliness: float = 0.0   # 热点时效性
    value: float = 0.0        # 内容价值延展性
    compliance: float = 0.0   # 合规风险度
    competition: float = 0.0  # 赛道竞争度


class BonusDetail(BaseModel):
    name: str
    points: float


class ScoreResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    topic_id: str = ""
    relevance_score: float = 0.0
    timeliness_score: float = 0.0
    value_score: float = 0.0
    compliance_score: float = 0.0
    competition_score: float = 0.0
    total_score: float = 0.0
    grade: str = "C"
    bonus_details: str = "[]"  # JSON string
    weight_mode: str = "new_account"
    platform: str = "wechat"
    positioning: str = "business_tech"
    scoring_version: str = "1.0"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ScoreRequest(BaseModel):
    weight_mode: str = "new_account"  # new_account | old_account
    platform: str = "wechat"          # wechat | toutiao | xiaohongshu
    positioning: str = "business_tech"  # business_tech | entertainment
    use_llm: bool = False             # Whether to use LLM for dimension scoring


# ── Matching ────────────────────────────────────────────────────────────

class MatchResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    topic_id: str = ""
    celebrity_id: str
    celebrity_name: str
    match_score: float = 0.0
    match_reason: str = ""
    rank: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class MatchRequest(BaseModel):
    use_llm: bool = True


# ── Review ──────────────────────────────────────────────────────────────

class ReviewAction(BaseModel):
    action: str = "confirm"  # confirm | discard | backup | adjust
    note: str = ""
    adjust_celebrities: Optional[list[dict]] = None  # For manual celebrity adjustment


class ReviewLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    topic_id: str
    action: str
    previous_status: str = ""
    new_status: str = ""
    operator: str = "admin"
    note: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ── Celebrity ───────────────────────────────────────────────────────────

class CelebritySummary(BaseModel):
    id: str
    name: str
    fields: list[str] = []
    status: str = ""
    has_full_dna: bool = False


class CelebrityDNA(BaseModel):
    id: str
    name: str
    fields: list[str] = []
    expression_dna: dict = {}
    thinking_tools: dict = {}
    decision_rules: dict = {}
    worldview: dict = {}
    boundaries_evolution: dict = {}
    suggested_topics: list[dict] = []


# ── Pipeline ────────────────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    title: str
    source_url: str = ""
    raw_content: str = ""
    weight_mode: str = "new_account"
    platform: str = "wechat"
    positioning: str = "business_tech"
    source_type: str = "manual"
    source_material: list[SourceMaterial] = []


# ── Filters ─────────────────────────────────────────────────────────────

class TopicFilter(BaseModel):
    status: str = ""
    grade: str = ""
    min_score: float = 0.0
    search: str = ""
    source_type: str = ""
    limit: int = 50
    offset: int = 0


# ── Collector ───────────────────────────────────────────────────────────

class URLImportRequest(BaseModel):
    url: str
    weight_mode: str = "new_account"
    platform: str = "wechat"
    positioning: str = "business_tech"


class HotItem(BaseModel):
    title: str
    url: str = ""
    platform: str = ""
    heat_score: float = 0.0
    rank: int = 0


class DistilledTopic(BaseModel):
    title: str
    core_topic: str = ""
    raw_content: str = ""
    source_url: str = ""
    source_platform: str = ""
    source_material: list[SourceMaterial] = []
    heat_level: str = "normal"
    is_valid: bool = True
    filter_reason: str = ""


class CollectionLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    batch_id: str
    source_name: str
    items_fetched: int = 0
    items_new: int = 0
    status: str = "running"
    error_message: str = ""
    started_at: str = ""
    completed_at: str = ""


class CollectStatus(BaseModel):
    enabled: bool = False
    running: bool = False
    last_run: str = ""
    last_status: str = "idle"
    interval_seconds: int = 3600

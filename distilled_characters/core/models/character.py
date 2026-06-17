"""Character and Material models."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Character(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    fields: list[str] = Field(default_factory=list)
    status: str = "created"  # created | materials_ready | distilling | completed | failed | expired
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict = Field(default_factory=dict)


class CharacterCreate(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    fields: list[str] = Field(default_factory=list)


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    aliases: Optional[list[str]] = None
    description: Optional[str] = None
    fields: Optional[list[str]] = None
    status: Optional[str] = None


class ThoughtTriple(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    material_id: str
    problem_scenario: str
    thinking_path: str
    conclusion: str
    tags: list[str] = Field(default_factory=list)


class Material(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    character_id: str
    source_type: str = "fragment_expression"
    # systematic_output | improv_expression | decision_behavior |
    # fragment_expression | third_party | timeline
    title: str = ""
    raw_content: str = ""
    cleaned_content: str = ""
    url: Optional[str] = None
    confidence: str = "B"  # S | A | B | C
    tags: list[str] = Field(default_factory=list)
    word_count: int = 0
    extracted_triples: list[ThoughtTriple] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class MaterialCreate(BaseModel):
    title: str = ""
    raw_content: str = ""
    url: Optional[str] = None
    source_type: str = "fragment_expression"
    confidence: str = "B"


class MaterialUpdate(BaseModel):
    title: Optional[str] = None
    raw_content: Optional[str] = None
    cleaned_content: Optional[str] = None
    url: Optional[str] = None
    source_type: Optional[str] = None
    confidence: Optional[str] = None
    tags: Optional[list[str]] = None

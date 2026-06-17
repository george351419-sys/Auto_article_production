"""High-level repository — domain-aware wrappers around storage."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from storage.base import AbstractStorage


class CharacterRepository:
    def __init__(self, storage: AbstractStorage) -> None:
        self.storage = storage
        self.collection = "characters"

    async def create(self, data: dict) -> dict:
        data.setdefault("created_at", datetime.now().isoformat())
        data.setdefault("updated_at", datetime.now().isoformat())
        data.setdefault("status", "created")
        data.setdefault("aliases", [])
        data.setdefault("description", "")
        data.setdefault("fields", [])
        data.setdefault("metadata", {})
        return await self.storage.create(self.collection, data)

    async def get(self, character_id: str) -> dict | None:
        return await self.storage.get(self.collection, character_id)

    async def list(self, query: Optional[str] = None) -> list[dict]:
        records = await self.storage.list(self.collection)
        if query:
            q = query.lower()
            records = [
                r for r in records
                if q in r.get("name", "").lower()
                or any(q in a.lower() for a in r.get("aliases", []))
                or q in r.get("description", "").lower()
            ]
        return sorted(records, key=lambda r: r.get("updated_at", ""), reverse=True)

    async def update(self, character_id: str, updates: dict) -> dict:
        updates["updated_at"] = datetime.now().isoformat()
        return await self.storage.update(self.collection, character_id, updates)

    async def delete(self, character_id: str) -> bool:
        return await self.storage.delete(self.collection, character_id)


class MaterialRepository:
    def __init__(self, storage: AbstractStorage) -> None:
        self.storage = storage
        self.collection = "materials"

    async def create(self, data: dict) -> dict:
        data.setdefault("created_at", datetime.now().isoformat())
        data.setdefault("source_type", "fragment_expression")
        data.setdefault("title", "")
        data.setdefault("raw_content", "")
        data.setdefault("cleaned_content", "")
        data.setdefault("url", None)
        data.setdefault("confidence", "B")
        data.setdefault("tags", [])
        data.setdefault("word_count", len(data.get("raw_content", "")))
        data.setdefault("extracted_triples", [])
        return await self.storage.create(self.collection, data)

    async def get(self, material_id: str) -> dict | None:
        return await self.storage.get(self.collection, material_id)

    async def list_for_character(
        self,
        character_id: str,
        source_type: Optional[str] = None,
        confidence: Optional[str] = None,
    ) -> list[dict]:
        filters = {"character_id": character_id}
        records = await self.storage.list(self.collection, filters)
        if source_type:
            records = [r for r in records if r.get("source_type") == source_type]
        if confidence:
            records = [r for r in records if r.get("confidence") == confidence]
        return sorted(records, key=lambda r: r.get("created_at", ""), reverse=True)

    async def update(self, material_id: str, updates: dict) -> dict:
        return await self.storage.update(self.collection, material_id, updates)

    async def delete(self, material_id: str) -> bool:
        return await self.storage.delete(self.collection, material_id)


class DistillationRepository:
    def __init__(self, storage: AbstractStorage) -> None:
        self.storage = storage
        self.collection = "distillations"

    async def create(self, data: dict) -> dict:
        data.setdefault("created_at", datetime.now().isoformat())
        data.setdefault("status", "pending")
        data.setdefault("version", 1)
        data.setdefault("pipeline_version", "1.0.0")
        data.setdefault("layers", {})
        data.setdefault("verification", None)
        data.setdefault("source_material_ids", [])
        data.setdefault("step_results", {})
        data.setdefault("error_message", None)
        return await self.storage.create(self.collection, data)

    async def get(self, distillation_id: str) -> dict | None:
        return await self.storage.get(self.collection, distillation_id)

    async def list_for_character(self, character_id: str) -> list[dict]:
        filters = {"character_id": character_id}
        records = await self.storage.list(self.collection, filters)
        return sorted(records, key=lambda r: r.get("created_at", ""), reverse=True)

    async def update(self, distillation_id: str, updates: dict) -> dict:
        return await self.storage.update(self.collection, distillation_id, updates)

    async def list_all(self) -> list[dict]:
        """Return all distillation records (for startup recovery)."""
        return await self.storage.list(self.collection)

    async def delete(self, distillation_id: str) -> bool:
        return await self.storage.delete(self.collection, distillation_id)

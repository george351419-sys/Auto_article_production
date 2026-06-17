"""JSON file-based storage implementation.

One JSON file per record. Simple, human-readable, zero-dependency.
Collection = subdirectory under the data root.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from storage.base import AbstractStorage


class FileStorage(AbstractStorage):
    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def _ensure_collection(self, collection: str) -> Path:
        coll_path = self.data_root / collection
        coll_path.mkdir(parents=True, exist_ok=True)
        return coll_path

    async def create(self, collection: str, record: dict) -> dict:
        coll_path = self._ensure_collection(collection)
        record_id = record.get("id") or self._new_id()
        record["id"] = record_id
        filepath = coll_path / f"{record_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        return record

    async def get(self, collection: str, record_id: str) -> dict | None:
        filepath = self._ensure_collection(collection) / f"{record_id}.json"
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    async def list(self, collection: str, filters: dict | None = None) -> list[dict]:
        coll_path = self._ensure_collection(collection)
        results = []
        for filepath in sorted(coll_path.glob("*.json")):
            with open(filepath, "r", encoding="utf-8") as f:
                record = json.load(f)
            if filters:
                if all(record.get(k) == v for k, v in filters.items()):
                    results.append(record)
            else:
                results.append(record)
        return results

    async def update(self, collection: str, record_id: str, updates: dict) -> dict:
        record = await self.get(collection, record_id)
        if record is None:
            raise FileNotFoundError(f"{collection}/{record_id} not found")
        record.update(updates)
        coll_path = self._ensure_collection(collection)
        filepath = coll_path / f"{record_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        return record

    async def delete(self, collection: str, record_id: str) -> bool:
        filepath = self._ensure_collection(collection) / f"{record_id}.json"
        if not filepath.exists():
            return False
        filepath.unlink()
        return True

    @staticmethod
    def _new_id() -> str:
        import uuid
        return str(uuid.uuid4())

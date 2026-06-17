"""Abstract storage interface — CRUD for all entity types."""
from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractStorage(ABC):
    """Generic CRUD storage for typed records.

    Concrete implementations: FileStorage (JSON files), or later SQLiteStorage.
    """

    @abstractmethod
    async def create(self, collection: str, record: dict) -> dict:
        """Insert a record. Returns the record with its generated id."""
        ...

    @abstractmethod
    async def get(self, collection: str, record_id: str) -> dict | None:
        """Get a single record by id."""
        ...

    @abstractmethod
    async def list(self, collection: str, filters: dict | None = None) -> list[dict]:
        """List records, optionally filtered by field=value pairs."""
        ...

    @abstractmethod
    async def update(self, collection: str, record_id: str, updates: dict) -> dict:
        """Partial update a record."""
        ...

    @abstractmethod
    async def delete(self, collection: str, record_id: str) -> bool:
        """Delete a record by id. Returns True if deleted."""
        ...

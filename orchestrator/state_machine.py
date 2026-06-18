"""State machine engine per LLD §2 and HLD §4.

11 states: collected → matched → writing → drafted → scored
→ reviewing → publishing → published, plus duplicated / failed / rejected.

Each transition is atomic (DB transaction) and writes an audit_log row.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

# ── State constants ──────────────────────────────────────────

STATES = (
    "collected",
    "duplicated",
    "matched",
    "writing",
    "drafted",
    "scored",
    "reviewing",
    "rejected",
    "publishing",
    "published",
    "failed",
)

# Whitelist of entity tables the state machine is allowed to touch.
# Anything else is a programming error (and we MUST refuse to render it
# into SQL — see _select_status_sql / _update_status_sql below).
_ENTITY_TABLES: frozenset[str] = frozenset({"topic", "article", "publish"})

# Pre-rendered, parameterised SQL keyed by entity_type. This is the
# single place in the orchestrator that has to turn a Python string into
# a SQL identifier; we keep it short, explicit, and never use f-strings
# on caller-supplied values.
_SELECT_STATUS_SQL = {
    "topic":   "SELECT status FROM topic WHERE id = ?",
    "article": "SELECT status FROM article WHERE id = ?",
    "publish": "SELECT status FROM publish WHERE id = ?",
}
_UPDATE_STATUS_SQL = {
    "topic":   "UPDATE topic   SET status = ?, updated_at = ? WHERE id = ?",
    "article": "UPDATE article SET status = ?, updated_at = ? WHERE id = ?",
    # publish has no updated_at column; tracked separately.
    "publish": "UPDATE publish SET status = ? WHERE id = ?",
}

TERMINAL_STATES = frozenset({"duplicated", "published", "rejected"})

# Legal transitions: from → set of valid to-states
TRANSITIONS: dict[str, set[str]] = {
    "collected":  {"matched", "duplicated"},
    "matched":    {"writing", "failed"},
    "writing":    {"drafted", "failed", "rejected"},
    "drafted":    {"scored", "failed"},
    "scored":     {"reviewing", "failed"},
    "reviewing":  {"publishing", "rejected", "failed"},
    "publishing": {"published", "failed"},
    "published":  set(),
    "duplicated": set(),
    "rejected":   set(),
    "failed":     {"matched", "writing", "drafted", "scored", "reviewing", "publishing"},  # retry
}


class StateMachineError(ValueError):
    """Raised when an illegal state transition is attempted."""
    pass


# ── Validation ───────────────────────────────────────────────

def validate_transition(from_state: str, to_state: str) -> None:
    """Raise StateMachineError if `from → to` is not allowed."""
    if from_state not in TRANSITIONS:
        raise StateMachineError(f"Unknown state: {from_state}")
    if to_state not in TRANSITIONS:
        raise StateMachineError(f"Unknown state: {to_state}")
    if to_state not in TRANSITIONS[from_state]:
        raise StateMachineError(
            f"Illegal transition: {from_state} → {to_state}"
        )


# ── Transition executor ──────────────────────────────────────

async def transition(
    db: aiosqlite.Connection,
    entity_type: str,      # "topic" | "article" | "publish"
    entity_id: str,
    to_state: str,
    trigger: str,          # "auto" | "user" | "cron" | "retry"
    *,
    from_state: str | None = None,
    actor: str = "system",
    payload: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    """Atomically update entity status and write audit_log.

    If from_state is None, the current state is read from DB.
    """
    if entity_type not in _ENTITY_TABLES:
        raise StateMachineError(f"Unsupported entity_type: {entity_type!r}")

    tid = trace_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(payload or {}, ensure_ascii=False)

    if from_state is None:
        cursor = await db.execute(_SELECT_STATUS_SQL[entity_type], (entity_id,))
        row = await cursor.fetchone()
        if row is None:
            raise StateMachineError(f"{entity_type} {entity_id} not found")
        from_state = row["status"]

    validate_transition(from_state, to_state)

    if entity_type == "publish":
        # publish has no updated_at column.
        await db.execute(_UPDATE_STATUS_SQL["publish"], (to_state, entity_id))
    else:
        await db.execute(_UPDATE_STATUS_SQL[entity_type], (to_state, now, entity_id))

    await db.execute(
        """INSERT INTO audit_log
           (entity_type, entity_id, from_state, to_state, trigger, actor, payload_json, trace_id, at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entity_type, entity_id, from_state, to_state, trigger, actor, payload_json, tid, now),
    )


# ── Convenience wrappers ─────────────────────────────────────

async def transition_topic(
    db: aiosqlite.Connection,
    topic_id: str,
    to_state: str,
    trigger: str,
    **kwargs: Any,
) -> None:
    await transition(db, "topic", topic_id, to_state, trigger, **kwargs)


async def transition_article(
    db: aiosqlite.Connection,
    article_id: str,
    to_state: str,
    trigger: str,
    **kwargs: Any,
) -> None:
    await transition(db, "article", article_id, to_state, trigger, **kwargs)


async def transition_publish(
    db: aiosqlite.Connection,
    publish_id: str,
    to_state: str,
    trigger: str,
    **kwargs: Any,
) -> None:
    await transition(db, "publish", publish_id, to_state, trigger, **kwargs)

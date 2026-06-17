"""Load celebrity models from the distilled_characters system.

Reads character JSON files (basic info) + distillation JSON files (full 5-layer DNA),
links them by character_id, picks the best distillation per celebrity.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from core.models import CelebrityDNA, CelebritySummary

logger = logging.getLogger("celebrity_loader")

CHARACTERS_DIR = "../distilled_characters/data/characters"
DISTILLATIONS_DIR = "../distilled_characters/data/distillations"

_cache: Optional[list[CelebrityDNA]] = None


def _load_characters() -> dict[str, dict]:
    """Load all character basic info from JSON files."""
    chars = {}
    chars_path = Path(CHARACTERS_DIR)
    if not chars_path.exists():
        logger.warning("Character directory not found: %s", chars_path)
        return chars
    for fp in chars_path.glob("*.json"):
        with open(fp, encoding="utf-8") as f:
            c = json.load(f)
        chars[c["id"]] = c
    return chars


def _load_distillations() -> list[dict]:
    """Load all distillation results from JSON files."""
    dists = []
    dist_path = Path(DISTILLATIONS_DIR)
    if not dist_path.exists():
        logger.warning("Distillation directory not found: %s", dist_path)
        return dists
    for fp in dist_path.glob("*.json"):
        with open(fp, encoding="utf-8") as f:
            dists.append(json.load(f))
    return dists


def _pick_best(distillations: list[dict]) -> dict | None:
    """Pick the best distillation: prefer completed with full DNA, largest file."""
    completed = [d for d in distillations if d.get("status") == "completed"]
    if not completed:
        return distillations[0] if distillations else None
    # Prefer those with actual expression_dna content
    with_dna = []
    for d in completed:
        layers = d.get("layers", {})
        expr = layers.get("expression_dna", {})
        if expr.get("language_tone") or expr.get("sentence_rhythm"):
            with_dna.append(d)
    candidates = with_dna if with_dna else completed
    # Pick the one with the most content (longest serialized layers)
    return max(candidates, key=lambda d: len(json.dumps(d.get("layers", {}), ensure_ascii=False)), default=None)


def load_celebrities(force_reload: bool = False) -> list[CelebrityDNA]:
    """Load all celebrity DNA models. Cached in memory after first load."""
    global _cache
    if _cache is not None and not force_reload:
        return _cache

    chars = _load_characters()
    dists = _load_distillations()

    # Group distillations by character_id
    by_char: dict[str, list[dict]] = {}
    for d in dists:
        cid = d.get("character_id", "")
        if cid not in by_char:
            by_char[cid] = []
        by_char[cid].append(d)

    celebrities = []
    for cid, char in chars.items():
        char_dists = by_char.get(cid, [])
        best = _pick_best(char_dists)
        layers = best.get("layers", {}) if best else {}

        dna = CelebrityDNA(
            id=cid,
            name=char.get("name", "Unknown"),
            fields=char.get("fields", []),
            expression_dna=_dictify(layers.get("expression_dna", {})),
            thinking_tools=_dictify(layers.get("thinking_tools", {})),
            decision_rules=_dictify(layers.get("decision_rules", {})),
            worldview=_dictify(layers.get("worldview", {})),
            boundaries_evolution=_dictify(layers.get("boundaries_evolution", {})),
            suggested_topics=layers.get("suggested_topics", []) if isinstance(layers.get("suggested_topics"), list) else [],
        )
        celebrities.append(dna)

    _cache = celebrities
    logger.info("Loaded %d celebrities with DNA data", len(celebrities))
    return celebrities


def _dictify(obj) -> dict:
    """Convert Pydantic model to dict, or return empty dict for non-dicts."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return {}


def get_celebrity_summaries() -> list[CelebritySummary]:
    """Get lightweight celebrity list (no full DNA)."""
    celebs = load_celebrities()
    return [
        CelebritySummary(
            id=c.id,
            name=c.name,
            fields=c.fields,
            status="completed",
            has_full_dna=bool(c.expression_dna.get("language_tone")),
        )
        for c in celebs
    ]


def get_celebrity_by_id(celebrity_id: str) -> CelebrityDNA | None:
    for c in load_celebrities():
        if c.id == celebrity_id:
            return c
    return None


def get_celebrity_by_name(name: str) -> CelebrityDNA | None:
    for c in load_celebrities():
        if c.name == name:
            return c
    return None

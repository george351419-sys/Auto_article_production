"""Dynamic prompt builder — assembles prompts with context interpolation."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.prompts import templates

if TYPE_CHECKING:
    from core.models.distillation import (
        DecisionRules,
        ExpressionDNA,
        FiveLayerOutput,
        ThinkingTools,
        Worldview,
    )


def build_step1_prompt(
    character_name: str,
    materials: list[dict],
) -> tuple[str, str]:
    """Build the prompt for Step 1: material classification and grading."""
    # Hard cap: ~60K chars total to fit within model context (along with system prompt + response)
    MAX_TOTAL_CHARS = 60000
    overhead = 2000  # formatting, headers, system prompt

    materials_text_parts = []
    chars_used = overhead
    per_item_cap = 5000

    for i, m in enumerate(materials):
        content = m.get("raw_content", "")
        title = m.get("title", f"素材{i+1}")
        header = f"### 素材 {i+1}: {title}\n```\n"
        footer = "\n```\n"
        item_overhead = len(header) + len(footer)

        remaining = MAX_TOTAL_CHARS - chars_used - item_overhead
        if remaining <= 200:
            break  # Stop adding materials if no space left

        truncated = content[:min(per_item_cap, remaining)]
        materials_text_parts.append(f"{header}{truncated}{footer}")
        chars_used += item_overhead + len(truncated)

    materials_text = "\n".join(materials_text_parts) if materials_text_parts else "（无素材，请标注为待补充）"

    return (
        templates.STEP1_SYSTEM,
        templates.STEP1_USER.format(
            character_name=character_name,
            materials_text=materials_text,
        ),
    )


def build_step2_prompt(
    character_name: str,
    materials: list[dict],
) -> tuple[str, str]:
    """Build the prompt for Step 2: thought-chain triple extraction."""
    # Hard cap: ~60K chars total
    MAX_TOTAL_CHARS = 60000
    overhead = 2000
    per_item_cap = 4000

    triples_text_parts = []
    chars_used = overhead

    for m in materials:
        confidence = m.get("confidence", "B")
        if confidence in ("B", "C"):
            # Still include B-grade if no S/A available, but truncate more
            per_item_cap = 2000
        content = m.get("cleaned_content") or m.get("raw_content", "")
        title = m.get("title") or m.get("id", "")
        header = f"## {title}\n"
        item_overhead = len(header) + 1  # +1 for trailing newline

        remaining = MAX_TOTAL_CHARS - chars_used - item_overhead
        if remaining <= 200:
            break

        truncated = content[:min(per_item_cap, remaining)]
        triples_text_parts.append(f"{header}{truncated}\n")
        chars_used += item_overhead + len(truncated)

    triples_text = "\n".join(triples_text_parts) if triples_text_parts else "（无有效素材）"

    return (
        templates.STEP2_SYSTEM,
        templates.STEP2_USER.format(
            character_name=character_name,
            triples_text=triples_text,
        ),
    )


def build_step3_prompt(
    character_name: str,
    triples: list[dict],
) -> tuple[str, str]:
    """Build the prompt for Step 3: thinking models and decision rules."""
    triples_json = json.dumps(triples, ensure_ascii=False, indent=2)

    return (
        templates.STEP3_SYSTEM,
        templates.STEP3_USER.format(
            character_name=character_name,
            triple_count=len(triples),
            triples_json=triples_json[:15000],  # Truncate if too large
        ),
    )


def build_step4_prompt(
    character_name: str,
    triples: list[dict],
    thinking_tools: dict,
    decision_rules: dict,
) -> tuple[str, str]:
    """Build the prompt for Step 4: unique perspective and worldview."""
    return (
        templates.STEP4_SYSTEM,
        templates.STEP4_USER.format(
            character_name=character_name,
            triple_count=len(triples),
            triples_json=json.dumps(triples, ensure_ascii=False, indent=2)[:8000],
            thinking_tools_json=json.dumps(thinking_tools, ensure_ascii=False, indent=2)[:5000],
            decision_rules_json=json.dumps(decision_rules, ensure_ascii=False, indent=2)[:5000],
        ),
    )


def build_step5_prompt(
    character_name: str,
    triples: list[dict],
    thinking_tools: dict,
    decision_rules: dict,
    worldview: dict,
) -> tuple[str, str]:
    """Build the prompt for Step 5: anti-patterns and cognitive evolution."""
    return (
        templates.STEP5_SYSTEM,
        templates.STEP5_USER.format(
            character_name=character_name,
            thinking_tools_json=json.dumps(thinking_tools, ensure_ascii=False, indent=2)[:4000],
            decision_rules_json=json.dumps(decision_rules, ensure_ascii=False, indent=2)[:4000],
            worldview_json=json.dumps(worldview, ensure_ascii=False, indent=2)[:4000],
            triples_json=json.dumps(triples, ensure_ascii=False, indent=2)[:6000],
        ),
    )


def build_step6_prompt(
    character_name: str,
    all_layers: dict,
    materials_summary: str,
) -> tuple[str, str]:
    """Build the prompt for Step 6: verification and packaging."""
    return (
        templates.STEP6_SYSTEM,
        templates.STEP6_USER.format(
            character_name=character_name,
            all_layers_json=json.dumps(all_layers, ensure_ascii=False, indent=2)[:12000],
            materials_summary=materials_summary[:3000],
        ),
    )


def build_topics_prompt(
    character_name: str,
    triples: list[dict],
    layers_summary: dict,
) -> tuple[str, str]:
    """Build the prompt for Step 7: topics recommendation."""
    return (
        templates.TOPICS_SYSTEM,
        templates.TOPICS_USER.format(
            character_name=character_name,
            triple_count=len(triples),
            triples_json=json.dumps(triples, ensure_ascii=False, indent=2)[:8000],
            layers_summary_json=json.dumps(layers_summary, ensure_ascii=False, indent=2)[:10000],
        ),
    )

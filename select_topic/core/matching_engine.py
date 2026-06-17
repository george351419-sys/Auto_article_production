"""LLM-driven celebrity matching engine.

For each topic, evaluates all celebrities against 6 matching dimensions
and returns TOP3 matches with scores and reasons.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

import httpx

from config import get_llm_config
from core.celebrity_loader import load_celebrities, get_celebrity_by_id
from core.models import CelebrityDNA, MatchResult

logger = logging.getLogger("matching_engine")

MATCHING_PROMPT = """你是一位资深内容策略师。请评估以下【话题】与【名人】的适配度。

## 话题
标题：{title}
内容：{content}

## 名人 DNA 模型：{celebrity_name}

### 1. 表达 DNA
{expression_dna}

### 2. 思维工具
{thinking_tools}

### 3. 决策规则
{decision_rules}

### 4. 世界观
{worldview}

### 5. 边界与演化
{boundaries_evolution}

### 6. 推荐话题库
{suggested_topics}

## 评估任务

请从以下 6 个维度评估话题与名人的匹配度（每维 0-100 分），然后给出综合匹配分：

1. **话题重合度**：话题与名人推荐话题库的重合程度
2. **价值观匹配度**：话题调性与名人世界观、核心价值观的契合度
3. **思维适配度**：话题内容适配名人思维工具、分析逻辑的程度
4. **风格契合度**：话题风格贴合名人表达 DNA、输出调性的程度
5. **边界安全性**：话题内容在名人可写边界内（无禁忌、无冲突）的程度
6. **演化一致性**：话题深度与名人风格演化轨迹的一致性

请严格按以下 JSON 格式返回（不要输出其他文字）：
{{"match_score": 85, "dimension_scores": {{"topic_overlap": 90, "value_match": 85, "thinking_fit": 80, "style_fit": 88, "boundary_safety": 95, "evolution_fit": 75}}, "reason": "一句话概述：该话题与名人的契合点和主要考量"}}
"""


def _format_celebrity_for_prompt(celeb: CelebrityDNA) -> dict[str, str]:
    """Format celebrity DNA into prompt-friendly strings."""
    def safe_json(obj, max_len=800):
        s = json.dumps(obj, ensure_ascii=False, indent=2)
        if len(s) > max_len:
            s = s[:max_len] + "\n...(truncated)"
        return s

    return {
        "celebrity_name": celeb.name,
        "expression_dna": safe_json({
            "language_tone": celeb.expression_dna.get("language_tone", ""),
            "sentence_rhythm": celeb.expression_dna.get("sentence_rhythm", ""),
            "argumentation_style": celeb.expression_dna.get("argumentation_style", ""),
            "rhetorical_habits": [
                h.get("pattern", "") for h in celeb.expression_dna.get("rhetorical_habits", [])
            ][:5],
            "catchphrases": [
                c.get("phrase", "") for c in celeb.expression_dna.get("catchphrases", [])
            ][:5],
        }),
        "thinking_tools": safe_json({
            "analysis_frameworks": [
                {"name": f.get("name", ""), "description": f.get("description", "")}
                for f in celeb.thinking_tools.get("analysis_frameworks", [])
            ][:3],
            "reasoning_paradigms": celeb.thinking_tools.get("reasoning_paradigms", [])[:5],
            "common_theories": celeb.thinking_tools.get("common_theories", [])[:5],
        }),
        "decision_rules": safe_json({
            "priority_rules": [
                r.get("rule", "") for r in celeb.decision_rules.get("priority_rules", [])
            ][:5],
            "tradeoff_principles": celeb.decision_rules.get("tradeoff_principles", [])[:5],
            "risk_tolerance": celeb.decision_rules.get("risk_tolerance", ""),
        }),
        "worldview": safe_json({
            "attention_focus": celeb.worldview.get("attention_focus", ""),
            "value_hierarchy": celeb.worldview.get("value_hierarchy", [])[:5],
            "unique_perspective": celeb.worldview.get("unique_perspective", ""),
            "cognitive_blind_spots": celeb.worldview.get("cognitive_blind_spots", [])[:3],
        }),
        "boundaries_evolution": safe_json({
            "value_red_lines": celeb.boundaries_evolution.get("value_red_lines", [])[:5],
            "expression_taboos": celeb.boundaries_evolution.get("expression_taboos", [])[:5],
            "anti_patterns": [
                a.get("pattern", "") for a in celeb.boundaries_evolution.get("anti_patterns", [])
            ][:3],
        }),
        "suggested_topics": safe_json([
            {"topic": t.get("topic", ""), "confidence": t.get("confidence", 0)}
            for t in celeb.suggested_topics[:5]
        ] if celeb.suggested_topics else "（无预设推荐话题）"),
    }


async def _call_llm(prompt: str) -> dict:
    """Call LLM API and parse JSON response."""
    llm = get_llm_config()
    url = f"{llm['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {llm['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": llm["model"],
        "messages": [
            {"role": "system", "content": "你是一个精确的内容策略评估系统。请只输出 JSON，不要输出其他内容。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"].strip()
    # Extract JSON from response (handle markdown code fences)
    json_match = re.search(r'\{[\s\S]*\}', content)
    if json_match:
        return json.loads(json_match.group())
    raise ValueError(f"Cannot parse JSON from LLM response: {content[:200]}")


async def _score_one_celebrity(
    title: str,
    content: str,
    celeb: CelebrityDNA,
    semaphore: asyncio.Semaphore,
) -> dict | None:
    """Score one celebrity's match with the topic."""
    try:
        formatted = _format_celebrity_for_prompt(celeb)
        prompt = MATCHING_PROMPT.format(
            title=title,
            content=content or title,
            **formatted,
        )
        async with semaphore:
            result = await _call_llm(prompt)
        return {
            "celebrity_id": celeb.id,
            "celebrity_name": celeb.name,
            "match_score": result.get("match_score", 0),
            "match_reason": result.get("reason", ""),
        }
    except Exception as e:
        logger.error("Match failed for %s: %s", celeb.name, str(e))
        return None


async def match_celebrities(
    title: str,
    content: str = "",
    max_celebrities: int = 9,
    top_n: int = 3,
) -> list[MatchResult]:
    """
    Match topic against all celebrities, return TOP N results.
    Runs all celebrity evaluations concurrently with a semaphore limit.
    """
    all_celebs = load_celebrities()
    # Only score celebrities with full DNA data
    candidates = [
        c for c in all_celebs[:max_celebrities]
        if c.expression_dna.get("language_tone")
    ]
    if not candidates:
        # Fallback: use all celebrities even without full DNA
        candidates = all_celebs[:max_celebrities]

    logger.info("Matching topic against %d celebrities", len(candidates))

    semaphore = asyncio.Semaphore(4)  # Max 4 concurrent LLM calls
    tasks = [
        _score_one_celebrity(title, content, celeb, semaphore)
        for celeb in candidates
    ]
    results = await asyncio.gather(*tasks)

    valid = [r for r in results if r is not None]
    # Sort by match_score descending
    valid.sort(key=lambda r: r["match_score"], reverse=True)

    matches = []
    for i, r in enumerate(valid[:top_n]):
        matches.append(MatchResult(
            celebrity_id=r["celebrity_id"],
            celebrity_name=r["celebrity_name"],
            match_score=round(r["match_score"], 1),
            match_reason=r["match_reason"],
            rank=i + 1,
        ))

    return matches


async def match_celebrities_rule_based(
    title: str,
    content: str = "",
    top_n: int = 3,
) -> list[MatchResult]:
    """
    Rule-based matching fallback (no LLM). Uses keyword overlap between
    topic and celebrity fields/suggested_topics.
    """
    all_celebs = load_celebrities()
    results = []

    for celeb in all_celebs:
        score = 55.0
        reasons = []

        text = f"{title} {content}".lower()

        # 1. Field keyword overlap — weighted by keyword specificity
        field_weight = 0
        for field in celeb.fields:
            for fkw in field.strip().split("，"):
                fkw = fkw.strip().lower()
                if not fkw:
                    continue
                if fkw in text:
                    field_weight += 10.0
                    reasons.append(f"领域「{fkw}」匹配")

        # 2. Suggested topics overlap — deeper semantic signal
        topic_weight = 0
        for st in celeb.suggested_topics:
            topic_name = st.get("topic", "").lower()
            if not topic_name:
                continue
            # Check multi-word overlap
            words = topic_name.split()
            matched_words = sum(1 for w in words if len(w) >= 2 and w in text)
            if len(words) > 0 and matched_words / len(words) >= 0.5:
                confidence = st.get("confidence", 0.5)
                topic_weight += 6.0 * confidence
                if len(reasons) < 4:
                    reasons.append(f"推荐话题「{st.get('topic','')}」相关(置信度{confidence:.0%})")

        # 3. DNA signal bonus — richer DNA means better match potential
        dna_richness = 0.0
        if celeb.expression_dna.get("language_tone"):
            dna_richness += 3.0
        if celeb.thinking_tools.get("analysis_frameworks"):
            dna_richness += 2.0
        if celeb.worldview.get("unique_perspective"):
            dna_richness += 2.0
        if celeb.boundaries_evolution.get("value_red_lines"):
            dna_richness += 1.0
        if celeb.suggested_topics:
            dna_richness += 1.0

        score += field_weight + topic_weight + dna_richness
        score = min(100.0, max(0.0, round(score, 1)))

        if not reasons:
            reasons.append("基于领域关键词的基础匹配")

        results.append({
            "celebrity_id": celeb.id,
            "celebrity_name": celeb.name,
            "match_score": score,
            "match_reason": "；".join(reasons[:4]),
        })

    results.sort(key=lambda r: r["match_score"], reverse=True)

    return [
        MatchResult(
            celebrity_id=r["celebrity_id"],
            celebrity_name=r["celebrity_name"],
            match_score=r["match_score"],
            match_reason=r["match_reason"],
            rank=i + 1,
        )
        for i, r in enumerate(results[:top_n])
    ]

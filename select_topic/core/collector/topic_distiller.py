"""LLM-based topic distillation.

Takes raw HotItem lists and:
 1. Uses LLM to extract core business/tech topics
 2. Filters out entertainment (明星八卦), politics (时政), and low-value items
 3. Returns distilled topics ready for scoring and storage

The raw hot items are consumed in memory and discarded after distillation.
Only the distilled topic (title, summary, source_material URLs) is kept.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from config import get_llm_config
from core.collector.base import HotItem, DistilledTopic

logger = logging.getLogger("topic_distiller")

DISTILL_PROMPT = """你是一个科技商业垂类内容筛选专家。请处理以下热点列表。

## 任务
1. 对每个热点，提取核心商业/科技话题，蒸馏为一条选题标题（15-30字，信息密度高）
2. 写2-3句内容摘要（涵盖事件主体、核心争议、用户利益关联）
3. 判断是否为娱乐八卦（明星、综艺、恋爱、吃瓜、粉丝）或纯时政（领导人、外交、政策文件），标记 is_valid=false
4. 判断与科技商业垂类（AI/大厂/创投/新能源/数字经济/产品/商业模式）的相关性
5. 估算热度等级：hot（热榜TOP10且持续上涨）、warm（热榜TOP50）、normal（其他）

## 热点列表
{items_json}

## 返回格式
请严格返回一个 JSON 数组，不要输出其他文字：
[
  {{
    "original_index": 0,
    "title": "蒸馏后的选题标题",
    "core_topic": "3-5字核心话题标签",
    "raw_content": "2-3句内容摘要",
    "heat_level": "hot|warm|normal",
    "is_valid": true,
    "filter_reason": ""
  }}
]
"""

SINGLE_URL_DISTILL_PROMPT = """你是一个科技商业垂类内容编辑。请从以下网页内容中提取选题。

## 网页标题：{page_title}
## 网页内容：{page_content}

## 任务
1. 提炼一个选题标题（15-30字，清晰传达核心话题）
2. 写2-3句内容摘要
3. 判断和科技商业的相关性，如果完全不相关（纯娱乐/纯时政/纯生活），标记 is_valid=false
4. 热度等级填 normal

请严格按 JSON 格式返回（不要输出其他文字）：
{{"title": "...", "core_topic": "...", "raw_content": "...", "heat_level": "normal", "is_valid": true, "filter_reason": ""}}
"""


async def distill_batch(items: list[HotItem]) -> list[DistilledTopic]:
    """Distill a batch of hot items through LLM.

    All raw items are consumed in memory. The LLM response is parsed
    and returned; no raw data is written to disk.

    For batches > 10 items, items are split into smaller chunks
    to avoid LLM response truncation.
    """
    CHUNK_SIZE = 10
    if not items:
        return []

    if len(items) > CHUNK_SIZE:
        all_results = []
        for i in range(0, len(items), CHUNK_SIZE):
            chunk = items[i:i + CHUNK_SIZE]
            chunk_results = await _distill_chunk(chunk)
            all_results.extend(chunk_results)
        return all_results

    return await _distill_chunk(items)


async def _distill_chunk(items: list[HotItem]) -> list[DistilledTopic]:
    """Distill a small chunk of hot items (up to 10)."""
    if not items:
        return []

    llm = get_llm_config()
    url = f"{llm['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {llm['api_key']}",
        "Content-Type": "application/json",
    }

    items_json = json.dumps([
        {"index": i, "title": item.title, "url": item.url, "platform": item.platform}
        for i, item in enumerate(items)
    ], ensure_ascii=False, indent=2)

    payload = {
        "model": llm["model"],
        "messages": [
            {"role": "system", "content": "你是一个精确的内容筛选系统。请只输出 JSON 数组，不要输出其他内容。"},
            {"role": "user", "content": DISTILL_PROMPT.format(items_json=items_json)},
        ],
        "temperature": 0.3,
        "max_tokens": 4000,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        # Extract JSON array — handle truncated responses by closing brackets
        json_match = re.search(r'\[[\s\S]*\]', content)
        if not json_match:
            # Try to fix truncated JSON: close any open array/objects
            logger.warning("Trying to fix truncated distill response")
            fixed = content.rstrip()
            brace_count = fixed.count('{') - fixed.count('}')
            bracket_count = fixed.count('[') - fixed.count(']')
            fixed = fixed + '}' * max(0, brace_count) + ']' * max(0, bracket_count)
            json_match = re.search(r'\[[\s\S]*\]', fixed)
        if not json_match:
            logger.error("Cannot parse distill response: %s", content[:200])
            return _fallback_distill(items)

        results = json.loads(json_match.group())

        distilled = []
        for entry in results:
            idx = entry.get("original_index", 0)
            item = items[idx] if idx < len(items) else None
            distilled.append(DistilledTopic(
                title=entry.get("title", item.title if item else ""),
                core_topic=entry.get("core_topic", ""),
                raw_content=entry.get("raw_content", ""),
                source_url=item.url if item else "",
                source_platform=item.platform if item else "",
                source_material=[{
                    "url": item.url,
                    "title": item.title,
                    "platform": item.platform,
                }] if item else [],
                heat_level=entry.get("heat_level", "normal"),
                is_valid=entry.get("is_valid", True),
                filter_reason=entry.get("filter_reason", ""),
            ))
        return distilled
    except Exception as e:
        logger.error("LLM distillation failed: %s", e)
        return _fallback_distill(items)


def _fallback_distill(items: list[HotItem]) -> list[DistilledTopic]:
    """Rule-based fallback when LLM is unavailable."""
    entertainment_kw = ["吃瓜", "离婚", "出轨", "绯闻", "八卦", "综艺", "选秀", "娱乐圈", "明星", "偶像", "粉丝", "应援", "恋爱"]
    politics_kw = ["习近平", "国务院", "政治局", "外交部", "中央", "军委", "两高", "人大"]

    results = []
    for item in items:
        text = item.title.lower()
        has_entertainment = any(kw in text for kw in entertainment_kw)
        has_politics = any(kw in text for kw in politics_kw)

        results.append(DistilledTopic(
            title=item.title,
            core_topic="",
            raw_content=item.title,
            source_url=item.url,
            source_platform=item.platform,
            source_material=[{"url": item.url, "title": item.title, "platform": item.platform}],
            heat_level="normal",
            is_valid=not (has_entertainment or has_politics),
            filter_reason="娱乐八卦" if has_entertainment else "时政相关" if has_politics else "",
        ))
    return results


async def distill_single_url(url: str, page_title: str, page_content: str) -> DistilledTopic:
    """Distill a single URL's content into a topic.

    The raw page_content is consumed in memory. After this function returns,
    the raw HTML/page text is discarded (not stored anywhere).
    """
    llm = get_llm_config()
    api_url = f"{llm['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {llm['api_key']}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": llm["model"],
        "messages": [
            {"role": "system", "content": "你是一个精确的内容提取系统。请只输出 JSON，不要输出其他内容。"},
            {"role": "user", "content": SINGLE_URL_DISTILL_PROMPT.format(
                page_title=page_title,
                page_content=page_content[:3000],
            )},
        ],
        "temperature": 0.3,
        "max_tokens": 500,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(api_url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"].strip()
    json_match = re.search(r'\{[\s\S]*\}', content)
    if json_match:
        result = json.loads(json_match.group())
    else:
        result = {}

    return DistilledTopic(
        title=result.get("title", page_title),
        core_topic=result.get("core_topic", ""),
        raw_content=result.get("raw_content", page_content[:300] if not result.get("raw_content") else ""),
        source_url=url,
        source_platform="",
        source_material=[{"url": url, "title": page_title, "platform": ""}],
        heat_level=result.get("heat_level", "normal"),
        is_valid=result.get("is_valid", True),
        filter_reason=result.get("filter_reason", ""),
    )

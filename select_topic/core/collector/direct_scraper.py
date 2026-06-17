"""Direct HTTP scraping of platform hot lists.

Each platform hot list is fetched via lightweight HTTP GET, parsed in memory,
and immediately returned as a list of HotItem. No HTML is ever written to disk.

Also provides TrendRadar integration:
 - Launch TrendRadar MCP server as subprocess
 - Call its tools to get hot items from each platform
 - Fall back to direct scraping if TrendRadar is unavailable
"""

from __future__ import annotations

import asyncio
from html import unescape
import json
import logging
import re
from typing import Optional
from urllib.parse import quote_plus, urljoin

import httpx

from core.collector.base import HotItem

logger = logging.getLogger("direct_scraper")

DEFAULT_PLATFORMS = ["toutiao", "weibo", "xiaohongshu", "newrank", "tophub"]

TOPHUB_URLS = [
    "https://tophub.today",
    "https://tophub.today/n/KqndgxeLl9",  # 微博热搜
    "https://tophub.today/n/Jb0vmloB1G",  # 百度热点
    "https://tophub.today/n/mproPpoq6O",  # 知乎热榜
]

NEWRANK_URLS = [
    "https://www.newrank.cn/public/info/list.html",
    "https://www.newrank.cn/ranklist/hotArticle",
]

# ── Headers ─────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


async def _fetch_json(url: str, client: httpx.AsyncClient) -> dict | list | None:
    """Fetch JSON from URL, return parsed data or None on failure."""
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url[:60], e)
        return None


async def _fetch_text(url: str, client: httpx.AsyncClient) -> str | None:
    """Fetch text from URL, return content or None on failure."""
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15.0)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url[:60], e)
        return None


def _clean_text(value: object) -> str:
    """Normalize text extracted from JSON or HTML."""
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _looks_like_hot_title(title: str) -> bool:
    """Keep likely hot-list titles and discard navigation/chrome text."""
    if not title:
        return False
    if len(title) < 4 or len(title) > 90:
        return False
    lower = title.lower()
    blocked = [
        "登录", "注册", "首页", "关于", "帮助", "更多", "全部", "提交", "广告",
        "copyright", "privacy", "terms", "javascript", "newrank", "今日热榜",
    ]
    if any(word in lower or word in title for word in blocked):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", title))


def _rank_heat_score(rank: int) -> float:
    """Normalize rank into a 0-100 heat score."""
    if rank <= 0:
        return 50.0
    return max(35.0, 100.0 - (rank - 1) * 2.5)


def _normalize_heat(raw_heat: object, rank: int) -> float:
    if isinstance(raw_heat, (int, float)):
        if raw_heat <= 100:
            return float(raw_heat)
        return min(100.0, max(40.0, float(raw_heat) / 10000 * 100))
    if isinstance(raw_heat, str):
        match = re.search(r"\d+(?:\.\d+)?", raw_heat.replace(",", ""))
        if match:
            return _normalize_heat(float(match.group()), rank)
    return _rank_heat_score(rank)


def _append_hot_item(
    items: list[HotItem],
    seen: set[str],
    *,
    title: object,
    url: object = "",
    base_url: str = "",
    platform: str,
    heat_score: object = None,
    rank: int | None = None,
    limit: int = 30,
) -> None:
    clean_title = _clean_text(title)
    if not _looks_like_hot_title(clean_title) or clean_title in seen:
        return
    item_rank = rank or len(items) + 1
    item_url = str(url or "").strip()
    if item_url.startswith("javascript:") or item_url.startswith("#"):
        item_url = ""
    if item_url and base_url:
        item_url = urljoin(base_url, item_url)
    seen.add(clean_title)
    items.append(HotItem(
        title=clean_title,
        url=item_url,
        platform=platform,
        heat_score=_normalize_heat(heat_score, item_rank),
        rank=item_rank,
    ))
    if len(items) > limit:
        del items[limit:]


def _parse_json_hot_items(data: object, platform: str, base_url: str, limit: int = 30) -> list[HotItem]:
    """Recursively extract hot-list-like entries from JSON payloads."""
    items: list[HotItem] = []
    seen: set[str] = set()
    title_keys = ("title", "name", "word", "query", "keyword", "topic", "desc", "content")
    url_keys = ("url", "link", "href", "source_url", "article_url", "share_url")
    heat_keys = ("heat", "hot", "hot_value", "hotValue", "score", "views", "readCount", "value")
    rank_keys = ("rank", "index", "sort", "position")

    def walk(node: object):
        if len(items) >= limit:
            return
        if isinstance(node, list):
            for child in node:
                walk(child)
                if len(items) >= limit:
                    break
            return
        if not isinstance(node, dict):
            return

        title = next((node.get(key) for key in title_keys if node.get(key)), "")
        if title:
            item_url = next((node.get(key) for key in url_keys if node.get(key)), "")
            heat = next((node.get(key) for key in heat_keys if node.get(key) is not None), None)
            raw_rank = next((node.get(key) for key in rank_keys if node.get(key) is not None), None)
            try:
                rank = int(raw_rank) if raw_rank is not None else len(items) + 1
            except (TypeError, ValueError):
                rank = len(items) + 1
            _append_hot_item(
                items, seen, title=title, url=item_url, base_url=base_url,
                platform=platform, heat_score=heat, rank=rank, limit=limit,
            )

        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value)

    walk(data)
    return items


def _parse_html_hot_items(html: str, platform: str, base_url: str, limit: int = 30) -> list[HotItem]:
    """Extract hot-list entries from public HTML pages."""
    items: list[HotItem] = []
    seen: set[str] = set()

    # Some modern pages embed their list data in application/json scripts.
    for script in re.findall(r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>', html, flags=re.IGNORECASE | re.DOTALL):
        try:
            json_items = _parse_json_hot_items(json.loads(unescape(script)), platform, base_url, limit)
        except Exception:
            continue
        for item in json_items:
            _append_hot_item(
                items, seen, title=item.title, url=item.url, platform=platform,
                heat_score=item.heat_score, rank=item.rank, limit=limit,
            )
            if len(items) >= limit:
                return items

    # Fallback: parse anchors. This covers TopHub board pages and many public rank pages.
    anchor_pattern = re.compile(
        r'<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in anchor_pattern.finditer(html):
        attrs = match.group("attrs")
        body = match.group("body")
        href_match = re.search(r'href=["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        title_match = re.search(r'title=["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        title = title_match.group(1) if title_match else body
        href = href_match.group(1) if href_match else ""
        _append_hot_item(
            items, seen, title=title, url=href, base_url=base_url,
            platform=platform, rank=len(items) + 1, limit=limit,
        )
        if len(items) >= limit:
            return items

    # Last resort: common data-title attributes.
    for title in re.findall(r'data-title=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
        _append_hot_item(items, seen, title=title, base_url=base_url, platform=platform, rank=len(items) + 1, limit=limit)
        if len(items) >= limit:
            break
    return items


# ── Platform collectors ─────────────────────────────────────────────────

async def scrape_toutiao(client: httpx.AsyncClient) -> list[HotItem]:
    """Scrape 今日头条热榜."""
    items = []
    try:
        url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
        data = await _fetch_json(url, client)
        if data and isinstance(data, dict):
            hot_list = data.get("data", [])
            for i, entry in enumerate(hot_list[:30]):
                title = entry.get("Title", "") or entry.get("title", "")
                item_url = entry.get("Url", "") or entry.get("url", "")
                heat = entry.get("HotValue", 0) or entry.get("heat", 0)
                if title:
                    items.append(HotItem(
                        title=str(title).strip(),
                        url=str(item_url).strip() if item_url else "",
                        platform="toutiao",
                        heat_score=min(100.0, float(heat) / 10000 * 100) if isinstance(heat, (int, float)) else 50,
                        rank=i + 1,
                    ))
    except Exception as e:
        logger.warning("Toutiao scrape failed: %s", e)
    return items


async def scrape_weibo(client: httpx.AsyncClient) -> list[HotItem]:
    """Scrape 微博热搜榜."""
    items = []
    try:
        url = "https://weibo.com/ajax/side/hotSearch"
        data = await _fetch_json(url, client)
        if data and isinstance(data, dict):
            hot_list = data.get("data", {}).get("realtime", [])
            for i, entry in enumerate(hot_list[:30]):
                word = entry.get("word", "") or entry.get("note", "")
                raw_hot = entry.get("num", 0) or entry.get("raw_hot", 0)
                if word:
                    items.append(HotItem(
                        title=str(word).strip(),
                        url=f"https://s.weibo.com/weibo?q={word}",
                        platform="weibo",
                        heat_score=min(100.0, float(raw_hot) / 10000 * 100) if isinstance(raw_hot, (int, float)) else 50,
                        rank=i + 1,
                    ))
    except Exception as e:
        logger.warning("Weibo scrape failed: %s", e)
    return items


async def scrape_xiaohongshu(client: httpx.AsyncClient) -> list[HotItem]:
    """Scrape 小红书热榜 (via web search page)."""
    items = []
    try:
        # Xiaohongshu doesn't have a simple open API; we use the explore feed
        url = "https://edith.xiaohongshu.com/api/sns/web/v1/homefeed"
        data = await _fetch_json(url, client)
        if data and isinstance(data, dict):
            notes = data.get("data", {}).get("items", [])
            for i, entry in enumerate(notes[:30]):
                note_card = entry.get("note_card", {}) or entry
                title = note_card.get("display_title", "") or note_card.get("title", "")
                note_id = entry.get("id", "") or note_card.get("note_id", "")
                if title and note_id:
                    items.append(HotItem(
                        title=str(title).strip(),
                        url=f"https://www.xiaohongshu.com/explore/{note_id}",
                        platform="xiaohongshu",
                        heat_score=60.0,
                        rank=i + 1,
                    ))
    except Exception as e:
        logger.warning("Xiaohongshu scrape failed: %s", e)
    return items


async def scrape_newrank(client: httpx.AsyncClient) -> list[HotItem]:
    """Scrape 新榜 public hot/rank pages.

    Newrank can require browser verification on some routes. We try public JSON
    first and then parse HTML pages opportunistically, returning an empty list
    instead of failing the whole collection cycle when blocked.
    """
    items: list[HotItem] = []
    seen: set[str] = set()

    json_urls = [
        "https://gw.newrank.cn/api/main/content/hot/list",
        "https://www.newrank.cn/xdnphb/data/weixinuser/searchWeixinData",
    ]
    try:
        for url in json_urls:
            data = await _fetch_json(url, client)
            if not data:
                continue
            for item in _parse_json_hot_items(data, "newrank", "https://www.newrank.cn", limit=30):
                item_url = item.url or f"https://www.newrank.cn/search?keyword={quote_plus(item.title)}"
                _append_hot_item(
                    items, seen, title=item.title, url=item_url, platform="newrank",
                    heat_score=item.heat_score, rank=len(items) + 1, limit=30,
                )
            if items:
                return items

        for url in NEWRANK_URLS:
            html = await _fetch_text(url, client)
            if not html:
                continue
            for item in _parse_html_hot_items(html, "newrank", url, limit=30):
                item_url = item.url or f"https://www.newrank.cn/search?keyword={quote_plus(item.title)}"
                _append_hot_item(
                    items, seen, title=item.title, url=item_url, platform="newrank",
                    heat_score=item.heat_score, rank=len(items) + 1, limit=30,
                )
            if items:
                break
    except Exception as e:
        logger.warning("Newrank scrape failed: %s", e)
    return items


async def scrape_tophub(client: httpx.AsyncClient) -> list[HotItem]:
    """Scrape 今日热榜 public pages."""
    items: list[HotItem] = []
    seen: set[str] = set()
    try:
        for url in TOPHUB_URLS:
            html = await _fetch_text(url, client)
            if not html:
                continue
            for item in _parse_html_hot_items(html, "tophub", url, limit=30):
                _append_hot_item(
                    items, seen, title=item.title, url=item.url, platform="tophub",
                    heat_score=item.heat_score, rank=len(items) + 1, limit=30,
                )
                if len(items) >= 30:
                    return items
    except Exception as e:
        logger.warning("TopHub scrape failed: %s", e)
    return items


# ── Scraper registry ────────────────────────────────────────────────────

SCRAPERS = {
    "toutiao": scrape_toutiao,
    "weibo": scrape_weibo,
    "xiaohongshu": scrape_xiaohongshu,
    "newrank": scrape_newrank,
    "tophub": scrape_tophub,
}


# ── Main entry point ────────────────────────────────────────────────────

async def scrape_all(platforms: list[str] | None = None) -> dict[str, list[HotItem]]:
    """Scrape all configured platforms. Returns {platform: [items]}."""
    return await try_scrape_all(platforms, use_trendradar=False, use_direct=True)


# ── TrendRadar integration via MCP subprocess ───────────────────────────

class TrendRadarClient:
    """Communicates with TrendRadar MCP server via subprocess JSON-RPC over stdio.

    Uses the standard MCP protocol:
      - Send: {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"...","arguments":{}}}
      - Receive: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"..."}]}}
    """

    def __init__(self, command: list[str], working_dir: str, timeout: float = 60.0):
        self.command = command
        self.working_dir = working_dir
        self.timeout = timeout
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0

    async def start(self) -> bool:
        """Launch TrendRadar MCP server subprocess."""
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=self.working_dir,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # Send initialize request
            self._request_id += 1
            await self._send_json({
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
            })
            resp = await asyncio.wait_for(self._read_json(), timeout=10.0)
            if resp and resp.get("result"):
                logger.info("TrendRadar MCP server started successfully")
                return True
            else:
                logger.warning("TrendRadar initialize failed: %s", resp)
                return False
        except Exception as e:
            logger.warning("Failed to start TrendRadar: %s", e)
            return False

    async def stop(self):
        """Terminate TrendRadar subprocess."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            logger.info("TrendRadar MCP server stopped")

    async def _send_json(self, data: dict):
        """Send a JSON-RPC message over stdin."""
        if not self._process or not self._process.stdin:
            return
        msg = json.dumps(data) + "\n"
        self._process.stdin.write(msg.encode())
        await self._process.stdin.drain()

    async def _read_json(self) -> Optional[dict]:
        """Read a JSON-RPC response from stdout."""
        if not self._process or not self._process.stdout:
            return None
        line = await self._process.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line.decode().strip())
        except json.JSONDecodeError:
            return None

    async def call_tool(self, tool_name: str, arguments: dict = None) -> Optional[dict]:
        """Call a TrendRadar MCP tool and return the result."""
        if not self._process:
            return None
        self._request_id += 1
        await self._send_json({
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        })
        try:
            resp = await asyncio.wait_for(self._read_json(), timeout=30.0)
            if resp and resp.get("result"):
                content = resp["result"].get("content", [])
                if content and isinstance(content, list):
                    return content[0] if isinstance(content[0], dict) else {"text": str(content[0])}
            return resp
        except asyncio.TimeoutError:
            logger.warning("TrendRadar tool '%s' timed out", tool_name)
            return None

    async def get_news(self) -> list[dict]:
        """Get latest news from TrendRadar."""
        result = await self.call_tool("get_latest_news")
        if result and "text" in result:
            try:
                return json.loads(result["text"])
            except json.JSONDecodeError:
                pass
        return []


_trendradar_client: Optional[TrendRadarClient] = None


async def _get_trendradar() -> Optional[TrendRadarClient]:
    """Get or initialize the TrendRadar client singleton."""
    from config import load_config
    global _trendradar_client
    if _trendradar_client is not None:
        return _trendradar_client

    cfg = load_config().get("collector", {}).get("trendradar", {})
    if not cfg.get("enabled", False):
        return None

    client = TrendRadarClient(
        command=cfg.get("command", ["uv", "run", "main.py"]),
        working_dir=cfg.get("working_dir", "../TrendRadar"),
        timeout=cfg.get("timeout_seconds", 60),
    )
    ok = await client.start()
    if ok:
        _trendradar_client = client
        return client
    else:
        logger.warning("TrendRadar not available, will use direct scraping")
        return None


async def scrape_via_trendradar(platforms: list[str] | None = None) -> dict[str, list[HotItem]]:
    """Use TrendRadar MCP to fetch hot items. Falls back to direct scraping."""
    client = await _get_trendradar()
    if not client:
        logger.info("TrendRadar unavailable, using direct scraping")
        return {}

    try:
        news = await client.get_news()
        if not news:
            logger.info("TrendRadar returned no news, using direct scraping")
            return {}

        results: dict[str, list[HotItem]] = {}
        target_platforms = platforms or DEFAULT_PLATFORMS
        for plat in target_platforms:
            results[plat] = []

        for i, item in enumerate(news):
            if not isinstance(item, dict):
                continue
            title = item.get("title", "") or item.get("word", "")
            url = item.get("url", "") or item.get("link", "")
            source = item.get("source", "") or item.get("platform", "")
            if not title:
                continue

            # Map TrendRadar source names to our platform keys
            plat = "toutiao" if "头条" in source or "toutiao" in source.lower() else \
                   "weibo" if "微博" in source or "weibo" in source.lower() else \
                   "xiaohongshu" if "小红书" in source or "xiaohongshu" in source.lower() else \
                   "newrank" if "新榜" in source or "newrank" in source.lower() else \
                   "tophub" if "今日热榜" in source or "tophub" in source.lower() else \
                   "toutiao"

            if plat in results:
                results[plat].append(HotItem(
                    title=str(title).strip(),
                    url=str(url).strip(),
                    platform=plat,
                    heat_score=60.0,
                    rank=len(results[plat]) + 1,
                ))

        total = sum(len(v) for v in results.values())
        logger.info("TrendRadar fetched %d items across %d platforms", total, len(target_platforms))
        return results
    except Exception as e:
        logger.warning("TrendRadar scrape failed: %s", e)
        return {}


async def try_scrape_all(platforms: list[str] | None = None,
                         use_trendradar: bool = True,
                         use_direct: bool = True) -> dict[str, list[HotItem]]:
    """Hybrid scraping: try TrendRadar first, fall back to direct scraping.

    Returns combined results. Only the final HotItem lists are kept in memory;
    all raw HTTP/API responses are discarded immediately after extraction.
    """
    results: dict[str, list[HotItem]] = {}
    target_platforms = platforms or DEFAULT_PLATFORMS

    # Initialize empty results for all platforms
    for plat in target_platforms:
        results[plat] = []

    # Try TrendRadar first
    trendradar_results = {}
    if use_trendradar:
        trendradar_results = await scrape_via_trendradar(target_platforms)
        for plat, items in trendradar_results.items():
            results[plat].extend(items)

    # Fill missing platforms with direct scraping
    if use_direct:
        for plat in target_platforms:
            # Only scrape platforms that TrendRadar didn't cover
            if plat not in trendradar_results or len(trendradar_results.get(plat, [])) == 0:
                scraper = SCRAPERS.get(plat)
                if scraper:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        try:
                            items = await scraper(client)
                            results[plat].extend(items)
                            logger.info("Direct scraped %s: %d items", plat, len(items))
                        except Exception as e:
                            logger.error("Direct scraper %s error: %s", plat, e)

    total = sum(len(v) for v in results.values())
    logger.info("Total collected: %d items", total)
    return results


async def fetch_url_content(url: str, client: httpx.AsyncClient = None) -> tuple[str, str]:
    """Fetch a single URL and return (title, body_text).

    Used for manual URL import: user pastes a link → we fetch the page →
    extract title and text → send to LLM distiller.
    The page HTML is discarded after extraction.
    """
    close_on_exit = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=20.0, headers=HEADERS)

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

        # Extract title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        page_title = title_match.group(1).strip() if title_match else url

        # Extract text: strip all HTML tags, scripts, styles
        text = html
        for tag in ['script', 'style', 'nav', 'header', 'footer']:
            text = re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # Limit to manageable size for LLM distillation
        if len(text) > 5000:
            text = text[:5000]

        return page_title, text
    except Exception as e:
        raise RuntimeError(f"Failed to fetch URL {url}: {e}")
    finally:
        if close_on_exit and client:
            await client.aclose()

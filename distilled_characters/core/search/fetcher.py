"""Web page content fetcher with readability extraction."""
from __future__ import annotations

import re

import httpx


class WebFetcher:
    async def fetch_content(self, url: str) -> str | None:
        """Fetch and extract readable text content from a URL."""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh)"},
                )
                resp.raise_for_status()
                html = resp.text
        except Exception:
            return None

        # Try readability extraction
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Remove scripts, styles, nav
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()

            # Try to find main content
            for selector in ["article", "main", '[role="main"]', ".content", ".post-content", ".article-content"]:
                main = soup.select_one(selector)
                if main:
                    soup = main
                    break

            text = soup.get_text(separator="\n", strip=True)
            # Collapse whitespace
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:10000]  # Limit to 10k chars
        except ImportError:
            pass

        # Fallback: basic HTML stripping
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:10000]

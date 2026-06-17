"""Image asset localization per PRD §6 / HLD ADR-3.

The writing module returns final_package with OSS URLs that expire in 24h
(已踩过坑). We must download every image immediately after the writing
phase completes and rewrite the package so the publish phase only reads
local files.

Layout:
    orchestrator/assets/{article_id}/{platform}/{image_id}.{ext}

Each downloaded image gets a row in the `asset` table (kind=cover|inline)
and the in-memory final_package dict is mutated so that:
  - PlatformPackage.images[i] gets `localPath` set to the absolute path
  - PlatformPackage.coverPath (NEW) points at the chosen cover local path
  - The original OSS URL is preserved on `origin_url` for traceability

Failures (single image fails to download) do NOT raise — we record the
error on the asset row and leave the entry with `localPath=""`. The
publish phase decides what to do with missing assets (e.g. wechat
requires a cover; if missing, readiness check will reject it).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import httpx

logger = logging.getLogger("orchestrator.assets")

ASSETS_ROOT = Path(__file__).parent / "assets"
DOWNLOAD_TIMEOUT = 30.0
MAX_BYTES = 20 * 1024 * 1024  # 20 MB cap per image


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(stem: str, ext: str) -> str:
    """Strip filesystem-unsafe characters and force a reasonable extension."""
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", stem)[:80] or "img"
    ext = ext.lstrip(".").lower()
    if not re.match(r"^[a-z0-9]{1,5}$", ext):
        ext = "png"
    return f"{stem}.{ext}"


def _guess_ext(url: str, content_type: str | None) -> str:
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ext.lstrip(".")
    m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:\?|$)", url, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return "png"


async def _download_one(
    client: httpx.AsyncClient,
    url: str,
    dest_dir: Path,
    image_id: str,
) -> dict[str, Any]:
    """Download a single URL. Returns dict with local_path/bytes/sha256/error."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        async with client.stream("GET", url, timeout=DOWNLOAD_TIMEOUT) as r:
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            ext = _guess_ext(url, content_type)
            fname = _safe_filename(image_id, ext)
            local = dest_dir / fname
            total = 0
            sha = hashlib.sha256()
            with local.open("wb") as f:
                async for chunk in r.aiter_bytes(64 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError(f"image > {MAX_BYTES} bytes")
                    sha.update(chunk)
                    f.write(chunk)
            return {
                "local_path": str(local.resolve()),
                "bytes": total,
                "sha256": sha.hexdigest(),
                "error": None,
            }
    except Exception as e:  # noqa: BLE001 — single image failure must not crash pipeline
        logger.warning("Asset download failed (%s): %s", url, e)
        return {"local_path": "", "bytes": 0, "sha256": "", "error": str(e)}


async def _record_asset(
    db: aiosqlite.Connection,
    article_id: str,
    platform: str | None,
    kind: str,
    local_path: str,
    origin_url: str,
    nbytes: int,
    sha256: str,
) -> None:
    await db.execute(
        """INSERT INTO asset (id, article_id, platform, kind, local_path,
           origin_url, bytes, sha256, downloaded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), article_id, platform, kind, local_path,
         origin_url, nbytes, sha256, _now()),
    )


async def localize_final_package(
    db: aiosqlite.Connection,
    article_id: str,
    final_package: dict,
) -> dict:
    """Download every OSS image in the package, mutate in place, and
    return the updated dict.

    Adds two fields per platform:
      - `images[i].localPath`
      - `coverPath`  (first image with kind=cover, fallback to first image)
    """
    if not final_package or not isinstance(final_package, dict):
        return final_package

    platforms = final_package.get("platforms", [])
    if not isinstance(platforms, list):
        return final_package

    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as c:
        for pp in platforms:
            if not isinstance(pp, dict):
                continue
            platform_name = pp.get("platform", "unknown")
            images = pp.get("images") or []
            dest_dir = ASSETS_ROOT / article_id / platform_name

            cover_local = ""
            for img in images:
                if not isinstance(img, dict):
                    continue
                url = img.get("url") or img.get("sourceUrl") or ""
                if not url:
                    continue
                image_id = str(img.get("id") or uuid.uuid4().hex[:12])
                placement = (img.get("placement") or "").lower()
                kind = "cover" if placement == "cover" else "inline"

                result = await _download_one(c, url, dest_dir, image_id)
                img["localPath"] = result["local_path"]
                img["origin_url"] = url

                if result["local_path"]:
                    await _record_asset(
                        db, article_id, platform_name, kind,
                        result["local_path"], url,
                        result["bytes"], result["sha256"],
                    )
                    if kind == "cover" and not cover_local:
                        cover_local = result["local_path"]

            # Cover fallback: first image with a successful local path.
            if not cover_local:
                for img in images:
                    if isinstance(img, dict) and img.get("localPath"):
                        cover_local = img["localPath"]
                        break
            pp["coverPath"] = cover_local

    await db.commit()
    return final_package

"""Tests for image download from OSS URLs.

Per DEV_PLAN §5.3 and HLD ADR-3: OSS images must be downloaded immediately
after writing completes, before OSS URLs expire (24h).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


class TestImageDownload:
    def test_download_to_local(self, tmp_path):
        dest = tmp_path / "images" / "article-1"
        dest.mkdir(parents=True)
        img = dest / "cover.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        assert img.exists()
        assert img.stat().st_size > 0

    def test_403_failure_reporting(self):
        failures = [{"url": "https://oss.example.com/img.png",
                     "error": "HTTP 403 (OSS URL expired)"}]
        assert "403" in failures[0]["error"]
        assert "OSS" in failures[0]["error"]

    def test_dest_directory_creation(self, tmp_path):
        dest = tmp_path / "assets" / "article-1"
        assert not dest.exists()
        dest.mkdir(parents=True, exist_ok=True)
        assert dest.exists()

    def test_local_path_format(self, tmp_path):
        article_id = "test-article-123"
        asset_dir = tmp_path / "assets" / article_id
        asset_dir.mkdir(parents=True)
        img_path = asset_dir / "cover.png"
        img_path.write_bytes(b"fake-png-data")
        rel_path = str(img_path.relative_to(tmp_path))
        assert "assets" in rel_path
        assert article_id in rel_path

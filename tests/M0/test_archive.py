"""M0 · archive helper 单元测试."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.archive import ArchiveError, archive_paths

pytestmark = pytest.mark.M0


def test_archive_moves_existing_paths(tmp_path: Path):
    src1 = tmp_path / "db1"
    src1.mkdir()
    (src1 / "f.txt").write_text("hello", encoding="utf-8")
    src2 = tmp_path / "single.db"
    src2.write_text("data", encoding="utf-8")

    archive_root = tmp_path / ".archive"
    fixed_now = datetime(2026, 6, 16, 10, 30, 0, tzinfo=timezone.utc)
    target = archive_paths([src1, src2], archive_root, label="init", now=fixed_now)

    assert target == archive_root / "init-20260616-103000"
    assert (target / "db1" / "f.txt").read_text(encoding="utf-8") == "hello"
    assert (target / "single.db").read_text(encoding="utf-8") == "data"
    # Sources must be gone
    assert not src1.exists()
    assert not src2.exists()


def test_archive_skips_missing_paths(tmp_path: Path):
    existing = tmp_path / "real"
    existing.mkdir()
    (existing / "x").write_text("x", encoding="utf-8")

    missing = tmp_path / "nope"

    archive_root = tmp_path / ".archive"
    target = archive_paths([existing, missing], archive_root)

    assert (target / "real" / "x").exists()
    assert not (target / "nope").exists()


def test_archive_label_used_in_dirname(tmp_path: Path):
    src = tmp_path / "x"
    src.write_text("y", encoding="utf-8")
    fixed_now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    target = archive_paths(
        [src], tmp_path / ".archive", label="M0", now=fixed_now
    )
    assert target.name == "M0-20260102-030405"


def test_archive_destination_collision_raises(tmp_path: Path):
    src = tmp_path / "x"
    src.write_text("y", encoding="utf-8")

    archive_root = tmp_path / ".archive"
    fixed_now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
    archive_paths([src], archive_root, now=fixed_now)

    src2 = tmp_path / "x"
    src2.write_text("z", encoding="utf-8")
    with pytest.raises(ArchiveError, match="already exists"):
        archive_paths([src2], archive_root, now=fixed_now)


def test_archive_creates_root_if_missing(tmp_path: Path):
    src = tmp_path / "x"
    src.write_text("y", encoding="utf-8")

    root = tmp_path / "deeply" / "nested" / ".archive"
    assert not root.exists()
    target = archive_paths([src], root)
    assert target.parent == root
    assert root.exists()


def test_archive_empty_source_list(tmp_path: Path):
    target = archive_paths([], tmp_path / ".archive", label="empty")
    assert target.exists()
    assert list(target.iterdir()) == []


def test_archive_dict_form_assigns_destination_names(tmp_path: Path):
    """dict form lets caller resolve basename collisions explicitly."""
    src1 = tmp_path / "mod_a"
    src1.mkdir()
    (src1 / "data").mkdir()
    (src1 / "data" / "f.txt").write_text("a", encoding="utf-8")

    src2 = tmp_path / "mod_b"
    src2.mkdir()
    (src2 / "data").mkdir()
    (src2 / "data" / "f.txt").write_text("b", encoding="utf-8")

    target = archive_paths(
        {"mod_a-data": src1 / "data", "mod_b-data": src2 / "data"},
        tmp_path / ".archive",
        label="m0",
    )
    assert (target / "mod_a-data" / "f.txt").read_text(encoding="utf-8") == "a"
    assert (target / "mod_b-data" / "f.txt").read_text(encoding="utf-8") == "b"


def test_archive_list_form_detects_collision(tmp_path: Path):
    src1 = tmp_path / "a" / "data"
    src1.mkdir(parents=True)
    src2 = tmp_path / "b" / "data"
    src2.mkdir(parents=True)

    with pytest.raises(ArchiveError, match="duplicate basenames"):
        archive_paths([src1, src2], tmp_path / ".archive")

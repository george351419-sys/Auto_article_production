"""Move legacy data dirs/files into a timestamped archive folder.

Used by M0 to retire v0 state before initializing the new schema.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path


class ArchiveError(RuntimeError):
    pass


def archive_paths(
    sources: dict[str, Path] | list[Path],
    archive_root: Path,
    label: str = "init",
    *,
    now: datetime | None = None,
) -> Path:
    """Move each source into archive_root/{label}-YYYYMMDD-HHMMSS/.

    `sources` accepts either:
    - dict[str, Path]: keys are destination names within the archive dir.
      Use this when multiple sources share the same basename
      (e.g. orchestrator/data + writing/data).
    - list[Path]: legacy form; src.name is used as destination name.
      Raises ArchiveError on name collisions.

    Missing sources are silently skipped (idempotent). Returns the timestamp
    directory path.
    """
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    target_dir = archive_root / f"{label}-{ts}"
    target_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(sources, dict):
        items: list[tuple[str, Path]] = list(sources.items())
    else:
        items = [(src.name, src) for src in sources]
        names = [n for n, _ in items]
        if len(set(names)) != len(names):
            raise ArchiveError(
                "duplicate basenames in sources list; "
                "use dict form to assign unique destination names"
            )

    for name, src in items:
        if not src.exists():
            continue
        dest = target_dir / name
        if dest.exists():
            raise ArchiveError(
                f"archive destination already exists: {dest} "
                "(timestamp collision — wait 1s and retry)"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))

    return target_dir

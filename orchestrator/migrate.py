"""Forward-only SQL migration runner.

Reads `migrations/00xx_*.sql` in lexical order and applies any whose
schema_version is greater than the value stored in `settings.schema_version`.

Each migration filename must start with a 4-digit number: `0001_init.sql`,
`0002_add_xxx.sql`, etc.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

# Support both `python -m orchestrator.migrate` (package import) and
# scripts that put orchestrator/ directly on sys.path (e.g. server_v2.py,
# the test conftest).
try:
    from .db import connect
except ImportError:  # pragma: no cover — defensive dual-import shim
    from db import connect  # type: ignore[no-redef]

MIGRATION_PATTERN = re.compile(r"^(\d{4})_[A-Za-z0-9_]+\.sql$")
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class MigrationError(RuntimeError):
    pass


def discover_migrations(migrations_dir: Path) -> list[tuple[int, Path]]:
    """Return [(version, path), ...] sorted ascending."""
    out: list[tuple[int, Path]] = []
    for p in sorted(migrations_dir.iterdir()):
        m = MIGRATION_PATTERN.match(p.name)
        if not m:
            continue
        out.append((int(m.group(1)), p))
    return out


def get_current_version(conn: sqlite3.Connection) -> int:
    """Return current schema_version from settings, or 0 if not yet initialized."""
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    return int(row["value"])


def migrate(
    db_path: str | Path,
    migrations_dir: Path | None = None,
) -> list[int]:
    """Run pending migrations. Returns versions applied (may be empty)."""
    mdir = migrations_dir or DEFAULT_MIGRATIONS_DIR
    if not mdir.is_dir():
        raise MigrationError(f"migrations dir not found: {mdir}")

    migrations = discover_migrations(mdir)
    if not migrations:
        raise MigrationError(f"no migrations found in {mdir}")

    applied: list[int] = []
    conn = connect(db_path)
    try:
        current = get_current_version(conn)
        for version, path in migrations:
            if version <= current:
                continue
            sql = path.read_text(encoding="utf-8")
            try:
                _execute_idempotent(conn, sql)
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                raise MigrationError(
                    f"migration {path.name} failed: {e}"
                ) from e
            applied.append(version)
        return applied
    finally:
        conn.close()


# SQLite has no "ADD COLUMN IF NOT EXISTS"; ALTER on an already-patched DB
# raises "duplicate column name". We treat that as already-applied so a
# migration file can re-run safely on a partially-patched database.
_IDEMPOTENT_PHRASES = ("duplicate column name", "already exists")


def _execute_idempotent(conn: sqlite3.Connection, sql: str) -> None:
    """Run each statement individually, swallowing duplicate-column errors."""
    for stmt in _split_statements(sql):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if any(p in str(e).lower() for p in _IDEMPOTENT_PHRASES):
                continue
            raise


def _split_statements(sql: str) -> list[str]:
    """Naive `;`-splitter that is good enough for our migration files
    (no embedded semicolons inside string literals).
    """
    out: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.split("--", 1)[0]  # strip line comments
        buf.append(line)
        if stripped.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        out.append(tail)
    return out


if __name__ == "__main__":  # pragma: no cover
    import sys

    db = sys.argv[1] if len(sys.argv) > 1 else "data/pipeline.db"
    applied = migrate(db)
    if applied:
        print(f"applied migrations: {applied}")
    else:
        print("schema already up to date")

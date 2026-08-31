"""Connection handling and migrations.

Plain sqlite3 with explicit SQL: the schema is small and the queries — ranking, diversity
capping, duplicate detection — are the interesting part (ADR 0002).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from resumaid.config import paths

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")


def connect(db_path: Path | None = None, *, migrate_on_connect: bool = True) -> sqlite3.Connection:
    path = db_path or paths().ensure().db
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False because FastAPI runs sync route handlers in a threadpool, so a
    # connection is opened on one thread and used on another. Safe here: get_db() hands out a
    # fresh connection per request, and WAL plus busy_timeout covers the reader/writer overlap.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    if migrate_on_connect:
        migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply any migration files not yet recorded. Returns the names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied: list[str] = []
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_file.name in done:
            continue
        # executescript() implicitly commits any pending transaction before it runs, so the
        # BEGIN/COMMIT has to live inside the script for the migration to be atomic.
        name_literal = "'" + sql_file.name.replace("'", "''") + "'"
        conn.executescript(
            "BEGIN;\n"
            + sql_file.read_text(encoding="utf-8")
            + f"\nINSERT INTO schema_migrations (name) VALUES ({name_literal});\nCOMMIT;"
        )
        applied.append(sql_file.name)
    return applied


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """An explicit transaction. ``isolation_level=None`` means we drive BEGIN/COMMIT ourselves."""
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")

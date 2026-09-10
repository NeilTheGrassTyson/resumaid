"""Shared request plumbing.

One SQLite connection per request. The database is a local file and there is exactly one user,
so this needs no pooling.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator

from resumaid.config import Settings
from resumaid.db import connect
from resumaid.ingest.interests import load_interests


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def get_settings() -> Settings:
    settings = Settings()
    # Before `resumaid init` there is no interests.yaml; the defaults hold until there is.
    with contextlib.suppress(FileNotFoundError, ValueError):
        settings.submissions_per_day = load_interests().throughput.submissions_per_day
    return settings

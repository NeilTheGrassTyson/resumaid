"""The ATS board registry, and the self-feeding mechanism behind it (ADR 0007).

The ATS APIs are per-company: each needs a board token, and the tool has no way to know which
companies exist. Rather than making the user curate that list by hand, every aggregator result
whose apply URL points at a known ATS contributes its token. Coverage compounds: an Adzuna
snippet today becomes a direct full-description source tomorrow, permanently, at no API cost.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from urllib.parse import urlparse

from resumaid.models import RawPosting, Source
from resumaid.util import iso, utcnow

#: How to recognize an ATS board from an apply URL, and where the token sits in the path.
_PATTERNS: list[tuple[Source, re.Pattern[str]]] = [
    (Source.GREENHOUSE, re.compile(r"^(?:boards|job-boards)\.greenhouse\.io$")),
    (Source.GREENHOUSE, re.compile(r"^boards-api\.greenhouse\.io$")),
    (Source.LEVER, re.compile(r"^jobs\.lever\.co$")),
    (Source.ASHBY, re.compile(r"^jobs\.ashbyhq\.com$")),
]

#: Path segments that are never a board token.
_NOT_TOKENS = {"embed", "job", "jobs", "v1", "boards", "api", "posting", "applications"}


@dataclass
class BoardRef:
    source: Source
    token: str


def board_from_url(url: str) -> BoardRef | None:
    """Extract an ATS board token from an apply URL, if it is one we can poll."""
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    for source, pattern in _PATTERNS:
        if not pattern.match(host):
            continue
        segments = [s for s in parsed.path.split("/") if s]
        for segment in segments:
            if segment.lower() in _NOT_TOKENS or segment.isdigit():
                continue
            return BoardRef(source, segment)
    return None


def register(
    conn: sqlite3.Connection,
    source: Source,
    token: str,
    *,
    company: str | None = None,
    via: str = "manual",
) -> bool:
    """Add a board. Returns True if it is new."""
    existing = conn.execute(
        "SELECT id FROM boards WHERE source = ? AND token = ?", (source.value, token)
    ).fetchone()
    if existing is not None:
        if company:
            conn.execute(
                "UPDATE boards SET company = COALESCE(company, ?) WHERE id = ?",
                (company, existing["id"]),
            )
        return False
    conn.execute(
        "INSERT INTO boards (source, token, company, added_at, discovered_via)"
        " VALUES (?,?,?,?,?)",
        (source.value, token, company, iso(utcnow()), via),
    )
    return True


def register_from_postings(conn: sqlite3.Connection, postings: list[RawPosting]) -> int:
    """Grow the registry from whatever the aggregators just returned."""
    added = 0
    for posting in postings:
        if posting.source in {Source.GREENHOUSE, Source.LEVER, Source.ASHBY}:
            continue  # already came from a board we poll
        ref = board_from_url(posting.apply_url)
        if ref and register(conn, ref.source, ref.token,
                            company=posting.company, via=posting.source.value):
            added += 1
    return added


def list_boards(conn: sqlite3.Connection, *, enabled_only: bool = True) -> list[sqlite3.Row]:
    sql = "SELECT * FROM boards"
    if enabled_only:
        sql += " WHERE enabled = 1"
    return conn.execute(sql + " ORDER BY source, token").fetchall()


def mark_polled(conn: sqlite3.Connection, board_id: int, status: str) -> None:
    conn.execute(
        "UPDATE boards SET last_polled_at = ?, last_status = ? WHERE id = ?",
        (iso(utcnow()), status, board_id),
    )


def disable(conn: sqlite3.Connection, board_id: int) -> None:
    """Stop polling a board — used when it 404s repeatedly."""
    conn.execute("UPDATE boards SET enabled = 0 WHERE id = ?", (board_id,))

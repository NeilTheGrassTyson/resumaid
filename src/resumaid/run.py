"""The discovery run: sources -> upsert -> registry -> score -> expire.

This is the whole automated half of the loop. It finds and prepares; it never sends. Nothing in
this module can reach the `approved` or `submitted` states — those are human actions
(constraint 1, ADR 0003).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import httpx

from resumaid.config import Settings
from resumaid.ingest.resume import list_resumes
from resumaid.match.pipeline import score_and_gate
from resumaid.models import Interests, Profile, RawPosting, Source
from resumaid.queue.store import expire_stale, upsert_posting
from resumaid.sources import adzuna, ashby, greenhouse, lever, usajobs
from resumaid.sources.base import FetchContext, make_client
from resumaid.sources.registry import list_boards, mark_polled, register_from_postings
from resumaid.util import iso, jdump, utcnow

_ATS = {
    Source.GREENHOUSE: greenhouse.fetch,
    Source.LEVER: lever.fetch,
    Source.ASHBY: ashby.fetch,
}


@dataclass
class RunReport:
    postings_seen: int = 0
    new_entries: int = 0
    boards_polled: int = 0
    boards_added: int = 0
    scored: int = 0
    queued: int = 0
    filtered: int = 0
    adjudicated: int = 0
    expired: int = 0
    sources_polled: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.postings_seen} postings seen",
            f"{self.new_entries} new",
            f"{self.queued} queued",
            f"{self.filtered} filtered",
        ]
        if self.boards_added:
            parts.append(f"{self.boards_added} new boards discovered")
        if self.expired:
            parts.append(f"{self.expired} expired")
        if self.errors:
            parts.append(f"{len(self.errors)} source errors")
        return ", ".join(parts)


def _search_terms(interests: Interests) -> list[str]:
    """Aggregator queries come from declared interests, never from anything baked in."""
    terms: list[str] = []
    for family in interests.role_families:
        terms.extend(family.keywords[:2] or [family.name])
    return list(dict.fromkeys(t for t in terms if t))[:4]


def _where(interests: Interests) -> str | None:
    metros = interests.locations.metros
    return metros[0] if metros else None


def fetch_all(
    conn: sqlite3.Connection,
    interests: Interests,
    settings: Settings,
    report: RunReport,
    *,
    ctx: FetchContext | None = None,
) -> list[RawPosting]:
    """Poll every configured source. One source failing never takes the run down."""
    owns_client = ctx is None
    client = make_client() if owns_client else None
    context = ctx or FetchContext(client)  # type: ignore[arg-type]
    postings: list[RawPosting] = []
    try:
        for board in list_boards(conn):
            source = Source(board["source"])
            fetcher = _ATS.get(source)
            if fetcher is None:
                continue
            try:
                found = fetcher(context, board["token"], board["company"])
                postings.extend(found)
                report.boards_polled += 1
                mark_polled(conn, board["id"], f"ok ({len(found)})")
            except httpx.HTTPStatusError as exc:
                mark_polled(conn, board["id"], f"http {exc.response.status_code}")
                report.errors.append(f"{source.value}/{board['token']}: {exc.response.status_code}")
            except Exception as exc:  # noqa: BLE001 - one bad board must not stop the run
                mark_polled(conn, board["id"], f"error: {exc}")
                report.errors.append(f"{source.value}/{board['token']}: {exc}")
        if report.boards_polled:
            report.sources_polled.append("ats")

        app_id = settings.secret("ADZUNA_APP_ID")
        app_key = settings.secret("ADZUNA_APP_KEY")
        if app_id and app_key:
            for term in _search_terms(interests):
                try:
                    postings.extend(
                        adzuna.fetch(context, app_id=app_id, app_key=app_key, what=term,
                                     where=_where(interests))
                    )
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"adzuna/{term}: {exc}")
            report.sources_polled.append("adzuna")

        usa_key = settings.secret("USAJOBS_API_KEY")
        usa_email = settings.secret("USAJOBS_EMAIL")
        if usa_key and usa_email:
            for term in _search_terms(interests):
                try:
                    postings.extend(
                        usajobs.fetch(context, api_key=usa_key, email=usa_email, keyword=term,
                                      location=_where(interests))
                    )
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"usajobs/{term}: {exc}")
            report.sources_polled.append("usajobs")
    finally:
        if owns_client and client is not None:
            client.close()
    return postings


def ingest(conn: sqlite3.Connection, postings: list[RawPosting], report: RunReport) -> set[int]:
    """Upsert every posting and grow the board registry from what the aggregators returned."""
    seen: set[int] = set()
    for posting in postings:
        result = upsert_posting(conn, posting)
        seen.add(result.entry_id)
        if result.created:
            report.new_entries += 1
    report.postings_seen = len(postings)
    report.boards_added = register_from_postings(conn, postings)
    return seen


def execute(
    conn: sqlite3.Connection,
    profile: Profile,
    interests: Interests,
    settings: Settings,
    *,
    use_llm: bool = False,
    use_research: bool = False,
    postings: list[RawPosting] | None = None,
) -> RunReport:
    """One full discovery run. ``postings`` may be supplied to skip fetching (tests)."""
    report = RunReport()
    started = iso(utcnow())
    cursor = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (started,))
    run_id = int(cursor.lastrowid or 0)

    found = postings if postings is not None else fetch_all(conn, interests, settings, report)
    seen = ingest(conn, found, report)

    summary = score_and_gate(
        conn, profile, interests, settings, list_resumes(conn),
        use_llm=use_llm, use_research=use_research,
    )
    report.scored = summary.scored
    report.queued = summary.queued
    report.filtered = summary.filtered
    report.adjudicated = summary.adjudicated

    # Only expire against sources we actually reached; a network failure must not retire the
    # whole queue.
    if seen or not report.errors:
        report.expired = expire_stale(conn, settings, seen)

    conn.execute(
        "UPDATE runs SET finished_at = ?, sources_polled = ?, postings_seen = ?, queued = ?,"
        " filtered = ?, notes = ? WHERE id = ?",
        (iso(utcnow()), jdump(report.sources_polled), report.postings_seen, report.queued,
         report.filtered, "; ".join(report.errors) or None, run_id),
    )
    return report

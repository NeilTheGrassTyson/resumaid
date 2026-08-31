"""Queue persistence: upsert with dedupe, slate assembly, and the human review actions.

Every mutating function here is the single implementation behind both the API route and its
CLI twin (ADR 0002), so the two can never drift.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from resumaid.config import Settings
from resumaid.models import (
    SOURCE_PRIORITY,
    Completeness,
    Confidence,
    QueueState,
    RawPosting,
    RejectionReason,
    Source,
)
from resumaid.queue import state as st
from resumaid.util import dedupe_key, iso, jdump, jload, parse_iso, utcnow


@dataclass
class UpsertResult:
    entry_id: int
    created: bool
    updated_from_better_source: bool = False


def upsert_posting(conn: sqlite3.Connection, posting: RawPosting) -> UpsertResult:
    """Insert a posting, or refresh the one already stored for it.

    Dedupe runs on ``dedupe_key``: the same role seen through several sources becomes one entry,
    keeping the record from the highest-priority source, since a direct ATS record carries the
    full description an aggregator only summarizes.
    """
    key = dedupe_key(posting.company, posting.title, posting.locations)
    ts = iso(utcnow())

    exact = conn.execute(
        "SELECT * FROM queue_entries WHERE source = ? AND source_job_id = ?",
        (posting.source.value, posting.source_job_id),
    ).fetchone()
    if exact is not None:
        conn.execute(
            "UPDATE queue_entries SET last_seen_at = ?, missed_runs = 0 WHERE id = ?",
            (ts, exact["id"]),
        )
        return UpsertResult(exact["id"], created=False)

    twin = conn.execute(
        "SELECT * FROM queue_entries WHERE dedupe_key = ? ORDER BY id LIMIT 1", (key,)
    ).fetchone()
    if twin is not None:
        # Every source this role has been seen in, minus whichever ends up primary.
        also = set(jload(twin["also_seen_in"], []) or [])
        also |= {posting.source.value, twin["source"]}
        incoming = SOURCE_PRIORITY[posting.source]
        existing = SOURCE_PRIORITY[Source(twin["source"])]
        also.discard(posting.source.value if incoming > existing else twin["source"])
        if incoming > existing:
            # A better source for a role we already have: take its record, keep our history.
            conn.execute(
                """UPDATE queue_entries SET source = ?, source_job_id = ?, apply_url = ?,
                       description_text = COALESCE(?, description_text),
                       description_source = CASE WHEN ? IS NOT NULL THEN 'api'
                                                 ELSE description_source END,
                       completeness = ?, posted_at = COALESCE(?, posted_at),
                       posted_at_precision = ?, department = COALESCE(?, department),
                       employment_type = COALESCE(?, employment_type),
                       compensation = COALESCE(?, compensation),
                       provenance_note = ?, last_seen_at = ?, missed_runs = 0,
                       also_seen_in = ?, scored_at = NULL
                   WHERE id = ?""",
                (
                    posting.source.value, posting.source_job_id, posting.apply_url,
                    posting.description_text, posting.description_text,
                    posting.completeness.value, iso(posting.posted_at),
                    posting.posted_at_precision.value, posting.department,
                    posting.employment_type, posting.compensation, posting.provenance_note,
                    ts, jdump(sorted(also)), twin["id"],
                ),
            )
            return UpsertResult(twin["id"], created=False, updated_from_better_source=True)
        conn.execute(
            "UPDATE queue_entries SET last_seen_at = ?, missed_runs = 0, also_seen_in = ?"
            " WHERE id = ?",
            (ts, jdump(sorted(also)), twin["id"]),
        )
        return UpsertResult(twin["id"], created=False)

    cur = conn.execute(
        """INSERT INTO queue_entries (
               source, source_job_id, dedupe_key, first_seen_at, last_seen_at, provenance_note,
               company, title, locations, remote, posted_at, posted_at_precision, closes_at,
               apply_url, department, employment_type, compensation, description_text,
               description_source, completeness, score_confidence, state, state_changed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            posting.source.value, posting.source_job_id, key, ts, ts, posting.provenance_note,
            posting.company, posting.title, jdump(posting.locations), int(posting.remote),
            iso(posting.posted_at), posting.posted_at_precision.value,
            posting.closes_at.isoformat() if posting.closes_at else None,
            posting.apply_url, posting.department, posting.employment_type, posting.compensation,
            posting.description_text,
            "api" if posting.description_text else None,
            posting.completeness.value, posting.confidence.value,
            QueueState.DISCOVERED.value, ts,
        ),
    )
    entry_id = int(cur.lastrowid or 0)
    conn.execute(
        "INSERT INTO state_log (queue_entry_id, to_state, actor, at, note)"
        " VALUES (?, ?, ?, ?, ?)",
        (entry_id, QueueState.DISCOVERED.value, st.PIPELINE, ts, f"from {posting.source.value}"),
    )
    return UpsertResult(entry_id, created=True)


def get(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM queue_entries WHERE id = ?", (entry_id,)).fetchone()


def slate(
    conn: sqlite3.Connection, settings: Settings, limit: int | None = None
) -> list[sqlite3.Row]:
    """The day's queue, ranked and diversity-capped.

    The slate is a ceiling on what is *shown*, never a quota to be filled. If three roles clear
    the bar, three are shown (constraint 5, REVIEW_QUEUE_SPEC.md §5.4).
    """
    wake_snoozed(conn)
    size = limit if limit is not None else slate_size(conn, settings)
    rows = conn.execute(
        "SELECT * FROM queue_entries WHERE state = ? ORDER BY rank_score DESC, first_seen_at DESC",
        (QueueState.QUEUED.value,),
    ).fetchall()
    return _cap_per_company(rows, settings.max_per_company_per_slate)[:size]


def _cap_per_company(rows: list[sqlite3.Row], cap: int) -> list[sqlite3.Row]:
    """Interleave so the top of the queue is not five roles at one employer.

    Round-robin over companies in rank order: the best role from each company first, then each
    company's second, and so on. Breadth counts (CLAUDE.md, Matching and targeting).
    """
    by_company: dict[str, list[sqlite3.Row]] = {}
    order: list[str] = []
    for row in rows:
        key = row["company"].lower()
        if key not in by_company:
            by_company[key] = []
            order.append(key)
        by_company[key].append(row)

    out: list[sqlite3.Row] = []
    for depth in range(cap):
        for key in order:
            bucket = by_company[key]
            if depth < len(bucket):
                out.append(bucket[depth])
    # Overflow beyond the cap trails behind, so nothing is lost if the slate is large.
    for key in order:
        out.extend(by_company[key][cap:])
    return out


def slate_size(conn: sqlite3.Connection, settings: Settings) -> int:
    import math

    return math.ceil(settings.submissions_per_day * surface_multiplier(conn, settings))


def surface_multiplier(conn: sqlite3.Connection, settings: Settings) -> float:
    """Tune how much to surface against the observed approval rate.

    Because the human rejects some of what is queued, the pipeline has to surface more than the
    target. This never touches the fit floor — only how many of the roles that already cleared
    it get shown.
    """
    lo, hi = settings.surface_multiplier_bounds
    since = iso(utcnow() - timedelta(days=14))
    row = conn.execute(
        """SELECT
               SUM(CASE WHEN to_state IN ('approved','submitted') THEN 1 ELSE 0 END) AS yes,
               SUM(CASE WHEN to_state IN ('approved','submitted','rejected')
                        THEN 1 ELSE 0 END) AS total
           FROM state_log WHERE actor = 'human' AND at >= ?""",
        (since,),
    ).fetchone()
    total = row["total"] or 0
    yes = row["yes"] or 0
    if total < 10 or yes == 0:
        return settings.surface_multiplier  # too little history to tune on
    return max(lo, min(hi, total / yes))


def wake_snoozed(conn: sqlite3.Connection) -> int:
    now = iso(utcnow())
    rows = conn.execute(
        "SELECT id FROM queue_entries WHERE state = ? AND snooze_until IS NOT NULL"
        " AND snooze_until <= ?",
        (QueueState.SNOOZED.value, now),
    ).fetchall()
    for row in rows:
        st.transition(
            conn, row["id"], QueueState.QUEUED, actor=st.SYSTEM,
            note="snooze elapsed", extra={"snooze_until": None},
        )
    return len(rows)


def expire_stale(conn: sqlite3.Connection, settings: Settings, seen_ids: set[int]) -> int:
    """Mark entries that have gone missing from their source for several runs."""
    rows = conn.execute(
        "SELECT id, missed_runs FROM queue_entries WHERE state IN (?, ?, ?)",
        (QueueState.QUEUED.value, QueueState.DISCOVERED.value, QueueState.SNOOZED.value),
    ).fetchall()
    expired = 0
    for row in rows:
        if row["id"] in seen_ids:
            continue
        missed = row["missed_runs"] + 1
        conn.execute("UPDATE queue_entries SET missed_runs = ? WHERE id = ?", (missed, row["id"]))
        if missed >= settings.expire_after_missing_runs:
            st.transition(
                conn, row["id"], QueueState.EXPIRED, actor=st.SYSTEM,
                note=f"not seen in {missed} runs",
            )
            expired += 1
    return expired


# --- human actions -------------------------------------------------------------------
# Each is the single implementation behind an API route and its CLI twin.


def approve(conn: sqlite3.Connection, entry_id: int, note: str | None = None) -> None:
    """Approve an entry for the ready tray.

    This prepares materials. It sends nothing, contacts no employer, and touches no form.
    """
    st.transition(conn, entry_id, QueueState.APPROVED, actor=st.HUMAN, note=note,
                  extra={"decision_note": note} if note else None)


def reject(
    conn: sqlite3.Connection,
    entry_id: int,
    reason: RejectionReason,
    note: str | None = None,
) -> None:
    st.transition(
        conn, entry_id, QueueState.REJECTED, actor=st.HUMAN, note=reason.value,
        extra={"rejection_reason": reason.value, "decision_note": note},
    )


def snooze(conn: sqlite3.Connection, entry_id: int, days: int = 3) -> None:
    until = iso(utcnow() + timedelta(days=days))
    st.transition(
        conn, entry_id, QueueState.SNOOZED, actor=st.HUMAN, note=f"{days}d",
        extra={"snooze_until": until},
    )


def unapprove(conn: sqlite3.Connection, entry_id: int) -> None:
    """Send an approved entry back to the queue — the 'I changed my mind' path."""
    st.transition(conn, entry_id, QueueState.QUEUED, actor=st.HUMAN, note="returned to queue")


def paste_description(conn: sqlite3.Connection, entry_id: int, text: str) -> None:
    """Upgrade a link-only entry with a description the human pasted in.

    The permitted manual path around a source the tool may not fetch — chiefly Workday, whose
    status is an open question in CLAUDE.md. The text is recorded as human-supplied, and the
    entry is marked for re-scoring at full confidence.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty description")
    conn.execute(
        """UPDATE queue_entries
              SET description_text = ?, description_source = 'human_paste', completeness = ?,
                  score_confidence = ?, scored_at = NULL
            WHERE id = ?""",
        (text, Completeness.FULL.value, Confidence.HIGH.value, entry_id),
    )


def counts_by_state(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        r["state"]: r["n"]
        for r in conn.execute("SELECT state, COUNT(*) AS n FROM queue_entries GROUP BY state")
    }


def stale_approved(conn: sqlite3.Connection, settings: Settings) -> list[sqlite3.Row]:
    """Approved entries the human never came back to record. See REVIEW_QUEUE_SPEC.md §6.4."""
    cutoff = iso(utcnow() - timedelta(hours=settings.approved_reconcile_hours))
    return conn.execute(
        "SELECT * FROM queue_entries WHERE state = ? AND state_changed_at <= ?"
        " ORDER BY state_changed_at",
        (QueueState.APPROVED.value, cutoff),
    ).fetchall()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("locations", "also_seen_in", "oa_expectation_evidence"):
        if key in d:
            d[key] = jload(d[key], [])
    if "score_breakdown" in d:
        d["score_breakdown"] = jload(d["score_breakdown"], None)
    if d.get("remote") is not None:
        d["remote"] = bool(d["remote"])
    return d


def age_days(row: sqlite3.Row) -> float | None:
    posted = parse_iso(row["posted_at"])
    if posted is None:
        return None
    return max(0.0, (utcnow() - posted).total_seconds() / 86400.0)

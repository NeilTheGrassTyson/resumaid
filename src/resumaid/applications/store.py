"""The durable application history.

Deliberately denormalized: company, title, location and URL are copied rather than referenced,
because postings get pulled down upstream and a history that goes blank when a job closes is
worthless (ADR 0008).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from resumaid.config import Settings
from resumaid.models import OAAssessment, Outcome, QueueState
from resumaid.queue import state as st
from resumaid.util import iso, jdump, jload, norm_company, norm_title, utcnow


@dataclass
class DuplicateHit:
    application_id: int
    company: str
    title: str
    submitted_at: str


def find_duplicate(conn: sqlite3.Connection, company: str, title: str) -> DuplicateHit | None:
    """Has this user already applied to this role?

    Re-surfacing a role you already applied to is the fastest way for a daily job-search tool to
    lose trust, so this runs in the gate before anything is queued.
    """
    row = conn.execute(
        "SELECT id, company, title, submitted_at FROM applications"
        " WHERE company_norm = ? AND title_norm = ? ORDER BY submitted_at DESC LIMIT 1",
        (norm_company(company), norm_title(title)),
    ).fetchone()
    if row is None:
        return None
    return DuplicateHit(row["id"], row["company"], row["title"], row["submitted_at"])


def record_submission(
    conn: sqlite3.Connection,
    entry_id: int,
    *,
    channel: str | None = None,
    note: str | None = None,
) -> int:
    """The human says: I submitted this.

    The only path to the ``submitted`` state. Writes the state transition (which the database
    trigger checks for a logged human actor) and the durable log row, in one transaction.
    """
    row = conn.execute("SELECT * FROM queue_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise LookupError(f"no queue entry {entry_id}")

    ts = iso(utcnow())
    st.transition(
        conn, entry_id, QueueState.SUBMITTED, actor=st.HUMAN, note=channel,
        extra={"submitted_at": ts, "submission_channel": channel, "confirmation_note": note},
    )

    resume = None
    if row["recommended_resume_id"]:
        r = conn.execute(
            "SELECT filename FROM resumes WHERE id = ?", (row["recommended_resume_id"],)
        ).fetchone()
        resume = r["filename"] if r else None

    locations = jload(row["locations"], []) or []
    cur = conn.execute(
        """INSERT INTO applications (
               queue_entry_id, company, title, company_norm, title_norm, location, source,
               apply_url, submitted_at, submission_channel, resume_used, resume_id,
               fit_score_at_submit, oa_expected, oa_expectation_confidence,
               oa_expectation_evidence, outcome, last_touched_at, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            entry_id, row["company"], row["title"], norm_company(row["company"]),
            norm_title(row["title"]), locations[0] if locations else None, row["source"],
            row["apply_url"], ts, channel, resume, row["recommended_resume_id"],
            row["fit_score"], row["oa_expected"], row["oa_expectation_confidence"],
            row["oa_expectation_evidence"], Outcome.PENDING.value, ts, note,
        ),
    )
    return int(cur.lastrowid or 0)


def list_applications(
    conn: sqlite3.Connection,
    *,
    outcome: str | None = None,
    company: str | None = None,
    since: str | None = None,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM applications WHERE 1=1"
    params: list[object] = []
    if outcome:
        sql += " AND outcome = ?"
        params.append(outcome)
    if company:
        sql += " AND company_norm LIKE ?"
        params.append(f"%{norm_company(company)}%")
    if since:
        sql += " AND submitted_at >= ?"
        params.append(since)
    sql += " ORDER BY submitted_at DESC"
    return conn.execute(sql, params).fetchall()


def update_application(conn: sqlite3.Connection, app_id: int, **fields: object) -> None:
    """Record what came back. Outcomes arrive by email days later, so this must be cheap."""
    allowed = {
        "outcome", "outcome_at", "oa_received", "oa_received_at", "oa_platform",
        "oa_due_at", "oa_completed_at", "notes", "submission_channel",
    }
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"not updatable: {sorted(bad)}")
    if not fields:
        return
    if "outcome" in fields and "outcome_at" not in fields:
        fields["outcome_at"] = iso(utcnow())
    # Recording an OA is the ground truth the prediction learns from, so keep the two in step.
    if fields.get("oa_received") and "oa_received_at" not in fields:
        fields["oa_received_at"] = iso(utcnow())
    fields["last_touched_at"] = iso(utcnow())
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE applications SET {sets} WHERE id = ?", [*fields.values(), app_id]
    )


def mark_ghosted(conn: sqlite3.Connection, settings: Settings) -> int:
    """The one status the tool infers on its own — and it is reversible."""
    cutoff = iso(utcnow() - timedelta(days=settings.ghost_after_days))
    cur = conn.execute(
        "UPDATE applications SET outcome = ?, outcome_at = ?, last_touched_at = ?"
        " WHERE outcome = ? AND submitted_at <= ?",
        (Outcome.GHOSTED.value, iso(utcnow()), iso(utcnow()), Outcome.PENDING.value, cutoff),
    )
    return cur.rowcount


def oa_history(conn: sqlite3.Connection, company: str) -> list[sqlite3.Row]:
    """Everything this user has recorded about assessments at one company."""
    return conn.execute(
        "SELECT title, oa_received, oa_platform, submitted_at FROM applications"
        " WHERE company_norm = ? AND oa_received IS NOT NULL ORDER BY submitted_at DESC",
        (norm_company(company),),
    ).fetchall()


def save_oa_assessment(conn: sqlite3.Connection, entry_id: int, a: OAAssessment) -> None:
    conn.execute(
        "UPDATE queue_entries SET oa_expected = ?, oa_expectation_confidence = ?,"
        " oa_expectation_evidence = ? WHERE id = ?",
        (a.expected.value, a.confidence.value,
         jdump([e.model_dump() for e in a.evidence]), entry_id),
    )


def stats(conn: sqlite3.Connection) -> dict[str, object]:
    total = conn.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
    by_outcome = {
        r["outcome"]: r["n"]
        for r in conn.execute("SELECT outcome, COUNT(*) AS n FROM applications GROUP BY outcome")
    }
    oa = conn.execute(
        "SELECT SUM(CASE WHEN oa_received = 1 THEN 1 ELSE 0 END) AS got,"
        " COUNT(oa_received) AS known FROM applications"
    ).fetchone()
    return {
        "total": total,
        "by_outcome": by_outcome,
        "oa_received": oa["got"] or 0,
        "oa_known": oa["known"] or 0,
    }

"""Queue routes. Each mutating route is the twin of a CLI command, calling the same function."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from resumaid.api.deps import get_db, get_settings
from resumaid.api.schemas import (
    ApproveIn,
    PasteIn,
    QueueEntryOut,
    RejectIn,
    ResumeOut,
    SlateOut,
    SnoozeIn,
    SubmitIn,
)
from resumaid.applications.store import record_submission
from resumaid.config import Settings
from resumaid.ingest.interests import load_interests, load_profile
from resumaid.ingest.resume import list_resumes
from resumaid.match.pipeline import score_and_gate
from resumaid.models import QueueState
from resumaid.queue import store as queue_store
from resumaid.queue.state import IllegalTransition, UnauthorizedActor
from resumaid.util import jload

router = APIRouter(prefix="/api/queue", tags=["queue"])


def _resume(conn: sqlite3.Connection, resume_id: int | None) -> ResumeOut | None:
    if not resume_id:
        return None
    row = conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    if row is None:
        return None
    return ResumeOut(id=row["id"], filename=row["filename"], path=row["path"],
                     is_master=bool(row["is_master"]), emphasis_summary=row["emphasis_summary"])


def to_out(conn: sqlite3.Connection, row: sqlite3.Row) -> QueueEntryOut:
    breakdown = jload(row["score_breakdown"], {}) or {}
    return QueueEntryOut(
        id=row["id"], state=row["state"], source=row["source"], company=row["company"],
        title=row["title"], locations=jload(row["locations"], []) or [],
        remote=bool(row["remote"]), posted_at=row["posted_at"],
        posted_at_precision=row["posted_at_precision"], apply_url=row["apply_url"],
        department=row["department"], compensation=row["compensation"],
        description_text=row["description_text"], description_source=row["description_source"],
        completeness=row["completeness"], provenance_note=row["provenance_note"],
        also_seen_in=jload(row["also_seen_in"], []) or [],
        fit_score=row["fit_score"], score_confidence=row["score_confidence"],
        rank_score=row["rank_score"], recency_factor=row["recency_factor"],
        dimensions=breakdown.get("dimensions", []),
        matched_signals=breakdown.get("matched_signals", []),
        missing_signals=breakdown.get("missing_signals", []),
        role_family=breakdown.get("role_family"),
        adjudication_note=breakdown.get("adjudication_note"),
        oa_expected=row["oa_expected"],
        oa_expectation_confidence=row["oa_expectation_confidence"],
        oa_expectation_evidence=jload(row["oa_expectation_evidence"], []) or [],
        recommended_resume=_resume(conn, row["recommended_resume_id"]),
        runner_up_resume=_resume(conn, row["runner_up_resume_id"]),
        selection_rationale=row["selection_rationale"],
        filter_reason=row["filter_reason"], state_changed_at=row["state_changed_at"],
    )


def _get_or_404(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row:
    row = queue_store.get(conn, entry_id)
    if row is None:
        raise HTTPException(404, f"no queue entry {entry_id}")
    return row


@router.get("", response_model=SlateOut)
def slate(
    limit: int | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SlateOut:
    rows = queue_store.slate(conn, settings, limit)
    counts = queue_store.counts_by_state(conn)
    return SlateOut(
        entries=[to_out(conn, r) for r in rows],
        slate_size=queue_store.slate_size(conn, settings),
        submissions_per_day=settings.submissions_per_day,
        total_queued=counts.get(QueueState.QUEUED.value, 0),
        counts=counts,
    )


@router.get("/filtered", response_model=list[QueueEntryOut])
def filtered(
    limit: int = 50, conn: sqlite3.Connection = Depends(get_db)
) -> list[QueueEntryOut]:
    """What the gate removed, and why — retained so the bar stays auditable."""
    rows = conn.execute(
        "SELECT * FROM queue_entries WHERE state='filtered'"
        " ORDER BY fit_score DESC NULLS LAST LIMIT ?", (limit,)
    ).fetchall()
    return [to_out(conn, r) for r in rows]


@router.get("/ready", response_model=list[QueueEntryOut])
def ready(conn: sqlite3.Connection = Depends(get_db)) -> list[QueueEntryOut]:
    """Approved and waiting for the human to apply. Nothing here has been sent."""
    rows = conn.execute(
        "SELECT * FROM queue_entries WHERE state='approved' ORDER BY state_changed_at"
    ).fetchall()
    return [to_out(conn, r) for r in rows]


@router.get("/{entry_id}", response_model=QueueEntryOut)
def show(entry_id: int, conn: sqlite3.Connection = Depends(get_db)) -> QueueEntryOut:
    return to_out(conn, _get_or_404(conn, entry_id))


@router.post("/{entry_id}/approve", response_model=QueueEntryOut)
def approve(
    entry_id: int, body: ApproveIn | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> QueueEntryOut:
    """Approve for the ready tray. Contacts no employer and submits nothing."""
    _get_or_404(conn, entry_id)
    try:
        queue_store.approve(conn, entry_id, body.note if body else None)
    except (IllegalTransition, UnauthorizedActor) as exc:
        raise HTTPException(409, str(exc)) from exc
    return to_out(conn, _get_or_404(conn, entry_id))


@router.post("/{entry_id}/reject", response_model=QueueEntryOut)
def reject(
    entry_id: int, body: RejectIn, conn: sqlite3.Connection = Depends(get_db)
) -> QueueEntryOut:
    _get_or_404(conn, entry_id)
    try:
        queue_store.reject(conn, entry_id, body.reason, body.note)
    except (IllegalTransition, UnauthorizedActor) as exc:
        raise HTTPException(409, str(exc)) from exc
    return to_out(conn, _get_or_404(conn, entry_id))


@router.post("/{entry_id}/snooze", response_model=QueueEntryOut)
def snooze(
    entry_id: int, body: SnoozeIn, conn: sqlite3.Connection = Depends(get_db)
) -> QueueEntryOut:
    _get_or_404(conn, entry_id)
    try:
        queue_store.snooze(conn, entry_id, body.days)
    except (IllegalTransition, UnauthorizedActor) as exc:
        raise HTTPException(409, str(exc)) from exc
    return to_out(conn, _get_or_404(conn, entry_id))


@router.post("/{entry_id}/unapprove", response_model=QueueEntryOut)
def unapprove(entry_id: int, conn: sqlite3.Connection = Depends(get_db)) -> QueueEntryOut:
    """'I changed my mind' — back to the queue, nothing recorded as sent."""
    _get_or_404(conn, entry_id)
    try:
        queue_store.unapprove(conn, entry_id)
    except (IllegalTransition, UnauthorizedActor) as exc:
        raise HTTPException(409, str(exc)) from exc
    return to_out(conn, _get_or_404(conn, entry_id))


@router.post("/{entry_id}/paste", response_model=QueueEntryOut)
def paste(
    entry_id: int,
    body: PasteIn,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QueueEntryOut:
    """Upgrade a link-only entry with a description the human supplied, then re-score."""
    _get_or_404(conn, entry_id)
    try:
        queue_store.paste_description(conn, entry_id, body.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        score_and_gate(conn, load_profile(), load_interests(), settings, list_resumes(conn))
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    return to_out(conn, _get_or_404(conn, entry_id))


@router.post("/{entry_id}/submitted", response_model=QueueEntryOut)
def submitted(
    entry_id: int, body: SubmitIn, conn: sqlite3.Connection = Depends(get_db)
) -> QueueEntryOut:
    """Record that the HUMAN submitted this application.

    The only route that can reach the `submitted` state, and it records a fact rather than
    causing one. Nothing here contacts an employer. CLAUDE.md constraint 1.
    """
    _get_or_404(conn, entry_id)
    try:
        record_submission(conn, entry_id, channel=body.channel, note=body.note)
    except (IllegalTransition, UnauthorizedActor) as exc:
        raise HTTPException(409, str(exc)) from exc
    return to_out(conn, _get_or_404(conn, entry_id))

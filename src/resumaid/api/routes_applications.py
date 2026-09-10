"""Application-log routes, including the CSV export."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from resumaid.api.deps import get_db, get_settings
from resumaid.api.schemas import ApplicationOut, ApplicationUpdateIn, StatsOut
from resumaid.applications import export as export_mod
from resumaid.applications.store import list_applications, mark_ghosted, stats, update_application
from resumaid.config import Settings

router = APIRouter(prefix="/api/applications", tags=["applications"])


def _to_out(row: sqlite3.Row) -> ApplicationOut:
    return ApplicationOut(
        id=row["id"], company=row["company"], title=row["title"], location=row["location"],
        source=row["source"], apply_url=row["apply_url"], submitted_at=row["submitted_at"],
        submission_channel=row["submission_channel"], resume_used=row["resume_used"],
        fit_score_at_submit=row["fit_score_at_submit"], oa_expected=row["oa_expected"],
        oa_received=None if row["oa_received"] is None else bool(row["oa_received"]),
        oa_received_at=row["oa_received_at"], oa_platform=row["oa_platform"],
        oa_due_at=row["oa_due_at"], outcome=row["outcome"], outcome_at=row["outcome_at"],
        notes=row["notes"],
    )


@router.get("", response_model=list[ApplicationOut])
def index(
    outcome: str | None = None,
    company: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[ApplicationOut]:
    mark_ghosted(conn, settings)
    return [_to_out(r) for r in list_applications(conn, outcome=outcome, company=company)]


@router.get("/stats", response_model=StatsOut)
def application_stats(conn: sqlite3.Connection = Depends(get_db)) -> StatsOut:
    return StatsOut(**stats(conn))  # type: ignore[arg-type]


@router.get("/export")
def export_csv(conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Download the history as CSV.

    utf-8-sig so Excel reads the encoding correctly on a double-click rather than mangling
    accented company names.
    """
    body = export_mod.to_csv(conn)
    return Response(
        content=body.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="applications.csv"'},
    )


@router.patch("/{app_id}", response_model=ApplicationOut)
def update(
    app_id: int, body: ApplicationUpdateIn, conn: sqlite3.Connection = Depends(get_db)
) -> ApplicationOut:
    """Record what came back. Answering the OA question is what trains the prediction."""
    row = conn.execute("SELECT id FROM applications WHERE id = ?", (app_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no application {app_id}")
    fields = body.model_dump(exclude_none=True)
    if "outcome" in fields:
        fields["outcome"] = fields["outcome"].value
    if "oa_received" in fields:
        fields["oa_received"] = int(fields["oa_received"])
    if fields:
        update_application(conn, app_id, **fields)
    updated = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    return _to_out(updated)

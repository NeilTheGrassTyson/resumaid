"""Profile, resumes, boards, and the run trigger."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from resumaid import run as run_mod
from resumaid.api.deps import get_db, get_settings
from resumaid.api.schemas import ResumeOut, RunIn, RunOut
from resumaid.config import Settings
from resumaid.ingest.interests import load_interests, load_profile
from resumaid.ingest.resume import list_resumes
from resumaid.models import Interests, Profile
from resumaid.sources.registry import list_boards

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/resumes", response_model=list[ResumeOut])
def resumes(conn: sqlite3.Connection = Depends(get_db)) -> list[ResumeOut]:
    return [
        ResumeOut(id=d.id or 0, filename=d.filename, path=d.path, is_master=d.is_master,
                  emphasis_summary=d.emphasis_summary)
        for d in list_resumes(conn)
    ]


@router.get("/profile", response_model=Profile)
def profile() -> Profile:
    try:
        return load_profile()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/interests", response_model=Interests)
def interests() -> Interests:
    try:
        return load_interests()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/boards")
def boards(conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in list_boards(conn, enabled_only=False)]


@router.post("/run", response_model=RunOut)
def trigger_run(
    body: RunIn | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RunOut:
    """Discover, score, and queue. Submits nothing — see CLAUDE.md constraint 1."""
    body = body or RunIn()
    try:
        report = run_mod.execute(
            conn, load_profile(), load_interests(), settings,
            use_llm=body.use_llm, use_research=body.use_research,
        )
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RunOut(
        postings_seen=report.postings_seen, new_entries=report.new_entries,
        queued=report.queued, filtered=report.filtered, boards_added=report.boards_added,
        expired=report.expired, errors=report.errors, summary=report.summary(),
    )

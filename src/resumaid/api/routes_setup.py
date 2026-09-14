"""Setup routes: resumes, the parsed profile, interests, boards, and aggregator credentials.

These make the browser sufficient for everything except installing the tool. Each is the twin
of a CLI command calling the same service function (ADR 0002) — the routes here own validation
and file handling, never the parsing or persistence logic, which already lives in `ingest` and
`sources.registry`. The credentials routes are write-only by design (ADR 0011): a value never
travels back to the browser once saved, only whether a key is configured.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import ValidationError

from resumaid.api.deps import get_db, get_settings
from resumaid.api.schemas import ResumeOut, SecretsIn, SecretsStatus
from resumaid.config import Settings, paths, set_secrets
from resumaid.ingest.interests import save_interests, save_profile
from resumaid.ingest.resume import (
    SUPPORTED,
    add_resume,
    list_resumes,
    parse_profile,
    resume_texts,
)
from resumaid.models import Interests, Profile, Source
from resumaid.sources.registry import board_from_url, disable, list_boards, register

router = APIRouter(prefix="/api", tags=["setup"])

#: Resumes are a page or two of text. Anything much larger is a mistake or a different file.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _to_out(doc) -> ResumeOut:
    return ResumeOut(
        id=doc.id or 0, filename=doc.filename, path=doc.path,
        is_master=doc.is_master, emphasis_summary=doc.emphasis_summary,
    )


@router.post("/resumes", response_model=ResumeOut, status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    is_master: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
) -> ResumeOut:
    """Accept a resume from the browser and register it.

    The file is validated and written to a temporary location first, so a rejected upload never
    leaves anything behind in the user's resumes directory.
    """
    name = Path(file.filename or "").name
    suffix = Path(name).suffix.lower()
    if not name or suffix not in SUPPORTED:
        raise HTTPException(
            400,
            f"unsupported resume format {suffix or '(none)'!r}; expected {sorted(SUPPORTED)}",
        )

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"{name} is {len(data) / 1_048_576:.1f}MB; the limit is "
                 f"{MAX_UPLOAD_BYTES // 1_048_576}MB"
        )
    if not data:
        raise HTTPException(400, f"{name} is empty")

    resumes_dir = paths().ensure().resumes
    with tempfile.TemporaryDirectory() as staging:
        staged = Path(staging) / name
        staged.write_bytes(data)
        try:
            # add_resume() extracts the text, so a scanned image or a corrupt file fails here —
            # before anything is copied into the user's own directory.
            doc = add_resume(conn, staged, is_master=is_master)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

        destination = resumes_dir / name
        shutil.copy2(staged, destination)

    # The record now points at the staging path; repoint it at the kept copy.
    conn.execute("UPDATE resumes SET path = ? WHERE id = ?", (str(destination), doc.id))
    _reparse_profile(conn)
    doc.path = str(destination)
    return _to_out(doc)


def _reparse_profile(conn: sqlite3.Connection) -> Profile:
    profile = parse_profile(resume_texts(conn))
    save_profile(profile)
    return profile


@router.delete("/resumes/{resume_id}", status_code=204)
def delete_resume(resume_id: int, conn: sqlite3.Connection = Depends(get_db)) -> None:
    """Forget a resume. The user's file is left where it is — this tool does not delete it."""
    row = conn.execute("SELECT id FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no resume {resume_id}")
    conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
    if list_resumes(conn):
        _reparse_profile(conn)


@router.post("/resumes/{resume_id}/master", response_model=ResumeOut)
def set_master(resume_id: int, conn: sqlite3.Connection = Depends(get_db)) -> ResumeOut:
    """Mark which document is the full master. Only one can be."""
    row = conn.execute("SELECT id FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no resume {resume_id}")
    conn.execute("UPDATE resumes SET is_master = (id = ?)", (resume_id,))
    doc = next(d for d in list_resumes(conn) if d.id == resume_id)
    return _to_out(doc)


@router.put("/profile", response_model=Profile)
def put_profile(profile: Profile) -> Profile:
    """Save a corrected profile.

    The parse is a starting point, not an authority — after the first run this file is the
    user's, and the matcher scores against whatever it says.
    """
    save_profile(profile)
    return profile


@router.post("/profile/reparse", response_model=Profile)
def reparse_profile(conn: sqlite3.Connection = Depends(get_db)) -> Profile:
    """Re-derive the profile from the uploaded resumes, discarding hand edits."""
    if not list_resumes(conn):
        raise HTTPException(400, "no resumes uploaded yet")
    return _reparse_profile(conn)


@router.put("/interests", response_model=Interests)
def put_interests(interests: Interests) -> Interests:
    """Save declared targeting.

    FastAPI validates the body against the model before this runs, so a malformed payload is
    rejected with field errors and interests.yaml is never left in a broken state.
    """
    try:
        save_interests(interests)
    except (OSError, ValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return interests


@router.get("/secrets", response_model=SecretsStatus)
def secrets_status(settings: Settings = Depends(get_settings)) -> SecretsStatus:
    """Which aggregator keys are configured. Never the values themselves (ADR 0011)."""
    return SecretsStatus(**{
        key: bool(settings.secret(key)) for key in SecretsStatus.model_fields
    })


@router.put("/secrets", status_code=204)
def put_secrets(body: SecretsIn) -> None:
    """Save one or more aggregator keys. A field left ``null`` leaves that key untouched.

    Write-only: there is no route that returns a saved value, and this one never echoes the
    body back. `secrets_status` above is how the frontend confirms a save landed.
    """
    pairs = {k: v for k, v in body.model_dump().items() if v}
    if not pairs:
        raise HTTPException(400, "no keys provided")
    set_secrets(pairs)


@router.post("/boards", status_code=201)
def add_board(
    payload: dict, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, object]:
    """Register an ATS board by URL, or by source and token."""
    url = (payload.get("url") or "").strip()
    source_name = (payload.get("source") or "").strip()
    token = (payload.get("token") or "").strip()
    company = (payload.get("company") or "").strip() or None

    if url:
        ref = board_from_url(url)
        if ref is None:
            raise HTTPException(
                400,
                "not a recognized ATS board URL — expected a greenhouse.io, lever.co or "
                "ashbyhq.com job board link",
            )
        source, token = ref.source, ref.token
    elif source_name and token:
        try:
            source = Source(source_name)
        except ValueError as exc:
            raise HTTPException(400, f"unknown source {source_name!r}") from exc
    else:
        raise HTTPException(400, "provide either a board url, or a source and token")

    added = register(conn, source, token, company=company, via="manual")
    return {"source": source.value, "token": token, "added": added}


@router.delete("/boards/{board_id}", status_code=204)
def remove_board(board_id: int, conn: sqlite3.Connection = Depends(get_db)) -> None:
    """Stop polling a board.

    Disables rather than deletes, so how it was discovered stays on the record and a
    self-registering board does not silently come back on the next run.
    """
    row = conn.execute("SELECT id FROM boards WHERE id = ?", (board_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no board {board_id}")
    disable(conn, board_id)


@router.post("/boards/{board_id}/enable", status_code=204)
def enable_board(board_id: int, conn: sqlite3.Connection = Depends(get_db)) -> None:
    row = conn.execute("SELECT id FROM boards WHERE id = ?", (board_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no board {board_id}")
    conn.execute("UPDATE boards SET enabled = 1 WHERE id = ?", (board_id,))


@router.get("/setup/status")
def setup_status(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """What still needs doing before a run will find anything useful."""
    resumes = list_resumes(conn)
    boards = list_boards(conn, enabled_only=False)
    try:
        from resumaid.ingest.interests import load_interests

        interests = load_interests()
        families = len(interests.role_families)
    except (FileNotFoundError, ValidationError):
        families = 0
    # Self-registering boards (CLAUDE.md, Decided) depend on an aggregator surfacing one — with
    # neither key configured, a run can never grow the board list on its own.
    aggregator_configured = bool(
        (settings.secret("ADZUNA_APP_ID") and settings.secret("ADZUNA_APP_KEY"))
        or (settings.secret("USAJOBS_API_KEY") and settings.secret("USAJOBS_EMAIL"))
    )
    return {
        "resumes": len(resumes),
        "role_families": families,
        "boards": len([b for b in boards if b["enabled"]]),
        "ready": bool(resumes) and families > 0,
        "aggregator_configured": aggregator_configured,
    }

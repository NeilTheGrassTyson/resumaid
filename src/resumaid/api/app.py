"""The local API, and the SPA it serves.

Bound to localhost by the CLI. No auth, no accounts, no tenancy: one user, one machine
(ADR 0002). Nothing here is designed to be exposed to a network.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from resumaid.api import routes_applications, routes_meta, routes_queue

UI_DIST = Path(__file__).resolve().parents[3] / "ui" / "dist"

app = FastAPI(
    title="resumaid",
    version="0.1.0",
    description=(
        "Local review queue for a personal job search. The API prepares applications; a human "
        "approves and submits them. No route submits an application to an employer."
    ),
)

app.include_router(routes_queue.router)
app.include_router(routes_applications.router)
app.include_router(routes_meta.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def mount_ui() -> None:
    """Serve the built SPA, so `resumaid serve` is one process and one URL."""
    if not UI_DIST.exists():
        return
    assets = UI_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        candidate = UI_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(UI_DIST / "index.html")


mount_ui()

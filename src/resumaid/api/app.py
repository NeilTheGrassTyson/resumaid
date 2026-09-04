"""The local API, and the SPA it serves.

Bound to localhost by the CLI. No auth, no accounts, no tenancy: one user, one machine
(ADR 0002). Nothing here is designed to be exposed to a network.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from resumaid.api import routes_applications, routes_meta, routes_queue, routes_setup

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
app.include_router(routes_setup.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def ui_is_built() -> bool:
    """Whether there is a built SPA to serve. `ui/dist` is a build artifact, not committed."""
    return (UI_DIST / "index.html").is_file()


BUILD_HINT = (
    "The review UI has not been built yet.\n\n"
    "  cd ui\n"
    "  npm install\n"
    "  npm run build\n\n"
    "Then run `resumaid serve` again. To skip the UI entirely, use `resumaid serve --api-only`."
)


def mount_ui() -> None:
    """Serve the built SPA, so `resumaid serve` is one process and one URL."""
    if not ui_is_built():
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

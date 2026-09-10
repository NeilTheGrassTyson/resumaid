"""Greenhouse job board API.

    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

Public, documented, no auth. The priority source per CLAUDE.md.

One caveat drives the ranking: Greenhouse exposes ``updated_at``, not a true creation date, so
posted_at_precision is ``approximate`` rather than ``exact``.
"""

from __future__ import annotations

from datetime import datetime

from resumaid.models import Completeness, DatePrecision, RawPosting
from resumaid.models import Source as Src
from resumaid.sources.base import FetchContext
from resumaid.util import html_to_text, parse_iso

BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


def parse(payload: dict, board_token: str, company_hint: str | None = None) -> list[RawPosting]:
    out: list[RawPosting] = []
    for job in payload.get("jobs", []) or []:
        location = (job.get("location") or {}).get("name")
        offices = [o.get("name") for o in job.get("offices") or [] if o.get("name")]
        locations = [loc for loc in [location, *offices] if loc]
        content = job.get("content") or ""
        text = html_to_text(content) if content else None
        departments = [d.get("name") for d in job.get("departments") or [] if d.get("name")]
        updated: datetime | None = parse_iso(job.get("updated_at"))
        out.append(
            RawPosting(
                source=Src.GREENHOUSE,
                source_job_id=str(job.get("id")),
                company=company_hint or board_token,
                title=job.get("title") or "(untitled)",
                locations=locations,
                remote=any("remote" in loc.lower() for loc in locations),
                posted_at=updated,
                # Greenhouse gives updated_at, not a creation date. Saying 'exact' here would
                # let an edited old posting masquerade as fresh.
                posted_at_precision=DatePrecision.APPROXIMATE if updated else DatePrecision.UNKNOWN,
                apply_url=job.get("absolute_url") or "",
                department=departments[0] if departments else None,
                description_text=text,
                completeness=Completeness.FULL if text else Completeness.LINK_ONLY,
                provenance_note=f"Greenhouse board {board_token}",
            )
        )
    return out


def fetch(
    ctx: FetchContext, board_token: str, company_hint: str | None = None
) -> list[RawPosting]:
    response = ctx.get(BASE.format(token=board_token))
    response.raise_for_status()
    return parse(response.json(), board_token, company_hint)

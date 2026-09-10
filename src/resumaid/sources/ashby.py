"""Ashby public job posting API.

    GET https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true

Public, no auth. No server-side filtering, so everything is filtered locally.
"""

from __future__ import annotations

from resumaid.models import Completeness, DatePrecision, RawPosting
from resumaid.models import Source as Src
from resumaid.sources.base import FetchContext
from resumaid.util import html_to_text, parse_iso

BASE = "https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true"


def parse(payload: dict, board_name: str, company_hint: str | None = None) -> list[RawPosting]:
    out: list[RawPosting] = []
    for job in payload.get("jobs", []) or []:
        location = job.get("location")
        secondary = [
            loc.get("location")
            for loc in job.get("secondaryLocations") or []
            if isinstance(loc, dict) and loc.get("location")
        ]
        locations = [loc for loc in [location, *secondary] if loc]
        text = job.get("descriptionPlain")
        if not text and job.get("descriptionHtml"):
            text = html_to_text(job["descriptionHtml"])
        published = parse_iso(job.get("publishedAt") or job.get("updatedAt"))
        comp = job.get("compensation") or {}
        summary = comp.get("compensationTierSummary") if isinstance(comp, dict) else None
        out.append(
            RawPosting(
                source=Src.ASHBY,
                source_job_id=str(job.get("id")),
                company=company_hint or payload.get("name") or board_name,
                title=job.get("title") or "(untitled)",
                locations=locations,
                remote=bool(job.get("isRemote"))
                or any("remote" in loc.lower() for loc in locations),
                posted_at=published,
                posted_at_precision=DatePrecision.EXACT if job.get("publishedAt")
                else (DatePrecision.APPROXIMATE if published else DatePrecision.UNKNOWN),
                apply_url=job.get("jobUrl") or job.get("applyUrl") or "",
                department=job.get("department") or job.get("team"),
                employment_type=job.get("employmentType"),
                compensation=summary,
                description_text=text,
                completeness=Completeness.FULL if text else Completeness.LINK_ONLY,
                provenance_note=f"Ashby board {board_name}",
            )
        )
    return out


def fetch(
    ctx: FetchContext, board_name: str, company_hint: str | None = None
) -> list[RawPosting]:
    response = ctx.get(BASE.format(name=board_name))
    response.raise_for_status()
    return parse(response.json(), board_name, company_hint)

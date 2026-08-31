"""USAJobs API.

    GET https://data.usajobs.gov/api/search

Official US federal API: free, documented, unambiguously permitted. Requires a registered email
in the ``User-Agent`` header and an ``Authorization-Key``.

Federal-civilian only, so it deepens one lane rather than adding breadth — but it is the one
source whose permitted status is not in any doubt.
"""

from __future__ import annotations

from datetime import date

from resumaid.models import Completeness, DatePrecision, RawPosting
from resumaid.models import Source as Src
from resumaid.sources.base import FetchContext
from resumaid.util import parse_iso

BASE = "https://data.usajobs.gov/api/search"


def parse(payload: dict) -> list[RawPosting]:
    out: list[RawPosting] = []
    result = payload.get("SearchResult") or {}
    for item in result.get("SearchResultItems", []) or []:
        job = item.get("MatchedObjectDescriptor") or {}
        locations = [
            loc.get("LocationName")
            for loc in job.get("PositionLocation") or []
            if loc.get("LocationName")
        ]
        details = job.get("UserArea", {}).get("Details", {}) or {}
        parts = [
            job.get("QualificationSummary"),
            details.get("JobSummary"),
            details.get("MajorDuties") if isinstance(details.get("MajorDuties"), str) else None,
        ]
        if isinstance(details.get("MajorDuties"), list):
            parts.append("\n".join(details["MajorDuties"]))
        text = "\n\n".join(p for p in parts if p) or None

        start = parse_iso(job.get("PublicationStartDate"))
        end = job.get("ApplicationCloseDate")
        remuneration = (job.get("PositionRemuneration") or [{}])[0]
        low, high = remuneration.get("MinimumRange"), remuneration.get("MaximumRange")
        comp = f"{low}–{high} {remuneration.get('RateIntervalCode', '')}".strip() if low else None
        schedules = [s.get("Name") for s in job.get("PositionSchedule") or [] if s.get("Name")]

        closes: date | None = None
        if end:
            parsed = parse_iso(end)
            closes = parsed.date() if parsed else None

        out.append(
            RawPosting(
                source=Src.USAJOBS,
                source_job_id=str(job.get("PositionID") or item.get("MatchedObjectId")),
                company=job.get("OrganizationName") or job.get("DepartmentName") or "(federal)",
                title=job.get("PositionTitle") or "(untitled)",
                locations=locations,
                remote=any(
                    "remote" in loc.lower() or "anywhere" in loc.lower() for loc in locations
                ),
                posted_at=start,
                posted_at_precision=DatePrecision.EXACT if start else DatePrecision.UNKNOWN,
                apply_url=job.get("ApplyURI", [None])[0] or job.get("PositionURI") or "",
                department=job.get("DepartmentName"),
                employment_type=schedules[0] if schedules else None,
                compensation=comp,
                description_text=text,
                completeness=Completeness.FULL if text else Completeness.LINK_ONLY,
                provenance_note="USAJobs (official federal API)",
                closes_at=closes,
            )
        )
    return out


def fetch(
    ctx: FetchContext,
    *,
    api_key: str,
    email: str,
    keyword: str,
    location: str | None = None,
    results_per_page: int = 50,
) -> list[RawPosting]:
    params: dict[str, object] = {
        "Keyword": keyword,
        "ResultsPerPage": results_per_page,
        "SortField": "opendate",
        "SortDirection": "desc",
    }
    if location:
        params["LocationName"] = location
    # USAJobs identifies callers by a registered email in the User-Agent. This is the one place
    # the user's address is sent, it goes only to the government API that requires it for
    # registration, and it never accompanies posting or profile data.
    response = ctx.get(
        BASE, params=params,
        headers={"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": api_key},
    )
    response.raise_for_status()
    return parse(response.json())

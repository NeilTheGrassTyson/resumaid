"""Adzuna aggregator API.

    GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}

Licensed API, app_id + app_key. Free tier is roughly 1,000 calls/month (~33/day), which is
ample for one user's saved searches at 50 results a page — but it is the binding constraint on
breadth, so queries are batched and kept few.

Returns **snippets, not full descriptions**, so most Adzuna-only entries arrive `partial`. Its
value is discovery: the apply URLs it returns are what grows the ATS board registry (ADR 0007).
"""

from __future__ import annotations

from resumaid.models import Completeness, DatePrecision, RawPosting
from resumaid.models import Source as Src
from resumaid.sources.base import FetchContext
from resumaid.util import parse_iso

BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


def parse(payload: dict) -> list[RawPosting]:
    out: list[RawPosting] = []
    for job in payload.get("results", []) or []:
        company = (job.get("company") or {}).get("display_name") or "(unknown)"
        location = (job.get("location") or {}).get("display_name")
        locations = [location] if location else []
        snippet = (job.get("description") or "").strip() or None
        created = parse_iso(job.get("created"))
        salary_min, salary_max = job.get("salary_min"), job.get("salary_max")
        comp = None
        if salary_min and salary_max:
            comp = f"{salary_min:,.0f}–{salary_max:,.0f}"
        out.append(
            RawPosting(
                source=Src.ADZUNA,
                source_job_id=str(job.get("id")),
                company=company,
                title=job.get("title") or "(untitled)",
                locations=locations,
                remote=any("remote" in loc.lower() for loc in locations),
                posted_at=created,
                posted_at_precision=DatePrecision.EXACT if created else DatePrecision.UNKNOWN,
                apply_url=job.get("redirect_url") or "",
                employment_type=job.get("contract_time"),
                compensation=comp,
                description_text=snippet,
                # A snippet is not a description. Saying otherwise would let the scorer treat a
                # two-line teaser as though it were the full posting.
                completeness=Completeness.PARTIAL if snippet else Completeness.LINK_ONLY,
                provenance_note=(
                    "surfaced via Adzuna; only a snippet is available from this source — "
                    "paste the full description to re-score at full confidence"
                ),
            )
        )
    return out


def fetch(
    ctx: FetchContext,
    *,
    app_id: str,
    app_key: str,
    what: str,
    where: str | None = None,
    country: str = "us",
    page: int = 1,
    results_per_page: int = 50,
    max_days_old: int = 30,
) -> list[RawPosting]:
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": results_per_page,
        "what": what,
        "max_days_old": max_days_old,
        "content-type": "application/json",
    }
    if where:
        params["where"] = where
    response = ctx.get(BASE.format(country=country, page=page), params=params)
    response.raise_for_status()
    return parse(response.json())

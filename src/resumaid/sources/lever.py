"""Lever postings API.

    GET https://api.lever.co/v0/postings/{company}?mode=json

Public, no auth. Unlike Greenhouse it returns a real ``createdAt``, so recency is exact.
"""

from __future__ import annotations

from datetime import UTC, datetime

from resumaid.models import Completeness, DatePrecision, RawPosting
from resumaid.models import Source as Src
from resumaid.sources.base import FetchContext

BASE = "https://api.lever.co/v0/postings/{company}?mode=json"


def parse(payload: list, company_token: str, company_hint: str | None = None) -> list[RawPosting]:
    out: list[RawPosting] = []
    for job in payload or []:
        categories = job.get("categories") or {}
        location = categories.get("location")
        locations = [location] if location else []
        text = job.get("descriptionPlain") or job.get("description") or None
        for section in job.get("lists") or []:
            content = section.get("content")
            if content:
                text = f"{text or ''}\n{section.get('text', '')}\n{content}"
        created = job.get("createdAt")
        posted = (
            datetime.fromtimestamp(created / 1000, tz=UTC)
            if isinstance(created, (int, float))
            else None
        )
        workplace = (job.get("workplaceType") or "").lower()
        out.append(
            RawPosting(
                source=Src.LEVER,
                source_job_id=str(job.get("id")),
                company=company_hint or company_token,
                title=job.get("text") or "(untitled)",
                locations=locations,
                remote=workplace == "remote"
                or any("remote" in loc.lower() for loc in locations),
                posted_at=posted,
                posted_at_precision=DatePrecision.EXACT if posted else DatePrecision.UNKNOWN,
                apply_url=job.get("hostedUrl") or job.get("applyUrl") or "",
                department=categories.get("team"),
                employment_type=categories.get("commitment"),
                description_text=text.strip() if text else None,
                completeness=Completeness.FULL if text else Completeness.LINK_ONLY,
                provenance_note=f"Lever board {company_token}",
            )
        )
    return out


def fetch(
    ctx: FetchContext, company_token: str, company_hint: str | None = None
) -> list[RawPosting]:
    response = ctx.get(BASE.format(company=company_token))
    response.raise_for_status()
    return parse(response.json(), company_token, company_hint)

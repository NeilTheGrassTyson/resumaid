"""Hard filters and the fit floor.

Per constraint 5, the matcher's job is to *remove* low-fit roles, not to rank them low and hope
the human notices. Everything that fails lands in `filtered` with the reason recorded, so the
gate's rejections stay auditable.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from resumaid.applications.store import find_duplicate
from resumaid.ingest.resume import DEGREE_ORDER
from resumaid.models import Interests, Profile, RawPosting
from resumaid.util import norm_company, norm_location

_CLEARANCE = re.compile(
    r"\b(security clearance|ts/sci|top secret|secret clearance|polygraph|q clearance)\b", re.I
)
_CITIZENSHIP = re.compile(
    r"\b(u\.?s\.? citizen(?:ship)?|must be a citizen|citizenship required|green card)\b", re.I
)
_DEGREE_REQUIRED = re.compile(
    r"\b(bachelor'?s?|b\.?s\.?|master'?s?|m\.?s\.?|ph\.?d|doctorate)\b[^.]{0,40}\b(required|degree)\b",
    re.I,
)
_SENIORITY_PATTERNS = [
    ("intern", r"\b(intern|internship|co-?op)\b"),
    ("new-grad", r"\b(new\s?grad|entry[- ]level|university grad|campus)\b"),
    ("junior", r"\b(junior|jr\.?|associate|\bi{1,2}\b|\b[12]\b)\b"),
    ("senior", r"\b(senior|sr\.?|staff|principal|lead|director|head of|vp\b)\b"),
]


@dataclass
class GateResult:
    passed: bool
    reason: str | None = None
    detail: str | None = None
    results: dict[str, str] = field(default_factory=dict)


def posting_seniority(posting: RawPosting) -> str | None:
    """Read seniority from the title first — it is far more reliable than the body text."""
    for level, pattern in _SENIORITY_PATTERNS:
        if re.search(pattern, posting.title, re.I):
            return level
    return None


def _location_ok(posting: RawPosting, interests: Interests) -> tuple[bool, str]:
    prefs = interests.locations
    if posting.remote and prefs.remote:
        return True, "remote, and you take remote"
    wanted = [norm_location(m) for m in prefs.metros]
    if not wanted and not prefs.metros:
        # No declared metros: remote-only unless the user is open to relocating.
        if prefs.remote and not posting.remote:
            if prefs.relocation in {"willing", "preferred"}:
                return True, "no metros declared; you're open to relocating"
            return False, "not remote, and no target metros declared"
        return True, "no location restriction declared"
    for loc in posting.locations:
        nloc = norm_location(loc)
        for want in wanted:
            if want and (want in nloc or nloc in want):
                return True, f"in {loc}"
    if prefs.relocation in {"willing", "preferred"}:
        where = ", ".join(posting.locations) or "unspecified"
        return True, f"outside your metros, but you'll relocate ({where})"
    if posting.remote and prefs.remote:
        return True, "remote"
    return False, f"location {', '.join(posting.locations) or 'unspecified'} is outside your metros"


def evaluate(
    conn: sqlite3.Connection,
    posting: RawPosting,
    profile: Profile,
    interests: Interests,
) -> GateResult:
    """Run the hard filters. First failure stops evaluation and records which filter failed."""
    results: dict[str, str] = {}
    text = posting.description_text or ""
    hay = f"{posting.title}\n{text}"

    # Exclusions first — the cheapest and most absolute.
    excluded = {norm_company(c) for c in interests.exclusions.companies}
    if norm_company(posting.company) in excluded:
        return GateResult(False, "excluded_company", posting.company, results)
    results["excluded_company"] = "not excluded"

    for kw in interests.exclusions.title_keywords:
        if kw and kw.lower() in posting.title.lower():
            return GateResult(False, "excluded_title_keyword", kw, results)
    results["excluded_title_keyword"] = "none matched"

    # Already applied. Re-surfacing these is the fastest way to lose the user's trust.
    dupe = find_duplicate(conn, posting.company, posting.title)
    if dupe is not None:
        return GateResult(
            False, "already_applied",
            f"applied {dupe.submitted_at[:10]} ({dupe.title})", results,
        )
    results["already_applied"] = "no prior application"

    # Location.
    ok, why = _location_ok(posting, interests)
    results["location"] = why
    if not ok:
        return GateResult(False, "wrong_location", why, results)

    # Seniority.
    wanted = {s.lower() for s in interests.hard_filters.seniority}
    level = posting_seniority(posting)
    if wanted and level and level not in wanted:
        return GateResult(False, "wrong_seniority", f"posting reads {level}", results)
    results["seniority"] = f"posting reads {level or 'unspecified'}"

    # Degree. Only filters when the posting demands more than the profile has.
    minimum = interests.hard_filters.degree_level_min
    have = profile.highest_degree_level
    if minimum and have and DEGREE_ORDER.index(have) < DEGREE_ORDER.index(minimum):
        return GateResult(
            False, "degree_level", f"you have {have}, filter wants {minimum}", results
        )
    results["degree_level"] = f"you have {have or 'unspecified'}"

    # Clearance and citizenship. A posting that requires what the user cannot offer is a
    # genuine hard fail, not a low score.
    if _CLEARANCE.search(hay) and not interests.hard_filters.clearance_required_ok:
        return GateResult(False, "clearance_required", "posting requires a clearance", results)
    results["clearance"] = "not required, or you're eligible"

    if _CITIZENSHIP.search(hay) and not interests.hard_filters.citizenship_required_ok:
        return GateResult(False, "citizenship_required", "posting requires citizenship", results)
    results["citizenship"] = "not required, or you're eligible"

    types = {t.lower() for t in interests.hard_filters.employment_types}
    if types and posting.employment_type and posting.employment_type.lower() not in types:
        return GateResult(False, "employment_type", posting.employment_type, results)
    results["employment_type"] = posting.employment_type or "unspecified"

    return GateResult(True, results=results)


def floor_for(family_name: str | None, interests: Interests, default_floor: float) -> float:
    """The fit floor that applies to this role, honoring any per-family bar.

    A family the user is lukewarm on stays reachable but is held to a higher bar — which is
    different from, and better than, merely ranking it lower.
    """
    if family_name:
        for fam in interests.role_families:
            if fam.name == family_name and fam.min_fit is not None:
                return max(default_floor, fam.min_fit)
    return default_floor

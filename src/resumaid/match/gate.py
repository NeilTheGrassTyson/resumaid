"""Hard filters and the fit floor.

Per constraint 5, the matcher's job is to *remove* low-fit roles, not to rank them low and hope
the human notices. Everything that fails lands in `filtered` with the reason recorded, so the
gate's rejections stay auditable.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from resumaid import geo
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


def _location_ok(
    posting: RawPosting, interests: Interests, profile: Profile | None = None
) -> tuple[bool, str]:
    """Whether a posting's location is workable at all.

    A location you would never take is a hard fail rather than a low score, per constraint 5.
    But the filter only fires when the tool is *sure*: if a place cannot be resolved, or you'd
    relocate anyway, the entry survives and the scorer discounts it instead.
    """
    prefs = interests.locations
    if posting.remote and prefs.remote:
        return True, "remote, and you take remote"
    if prefs.will_relocate:
        where = ", ".join(posting.locations) or "unspecified"
        return True, f"you'd relocate ({where})"

    declared = prefs.all_places()

    # An explicitly named place or state always passes.
    posting_states = {geo.state_of(loc) for loc in posting.locations} - {None}
    for pref in declared:
        if pref.state and pref.state.upper() in posting_states:
            return True, f"in {pref.state.upper()}, a state you named"
        if pref.place:
            pref_city = geo.parse_place(pref.place)[0]
            for loc in posting.locations:
                if pref_city and pref_city == geo.parse_place(loc)[0]:
                    return True, f"in {pref.place}"
                if norm_location(pref.place).split(",")[0] in norm_location(loc):
                    return True, f"in {loc}"

    home = prefs.home or (profile.locations[0] if profile and profile.locations else None)
    radius = prefs.max_distance_miles

    if home and radius:
        distances = [geo.distance_between(home, loc) for loc in posting.locations]
        known = [d for d in distances if d is not None]
        if known:
            nearest = min(known)
            if nearest <= radius:
                return True, f"{nearest:.0f}mi from {home}"
            return False, (
                f"{nearest:.0f}mi from {home}, beyond your {radius:.0f}mi radius, "
                "and you're not relocating"
            )

    # A location the place table doesn't carry is not evidence of anything. Filtering on it
    # would hide roles for a reason the user can't see or act on, so let it through and let the
    # scorer discount it — it lands low in the queue rather than vanishing.
    if posting.locations and not any(geo.resolve(loc) for loc in posting.locations):
        where = ", ".join(posting.locations)
        return True, f"could not place {where}; not filtering on a location it can't resolve"

    if not declared:
        if prefs.remote and not posting.remote:
            return False, "not remote, and you've declared no places you'd work"
        return True, "no location restriction declared"

    where = ", ".join(posting.locations) or "unspecified"
    return False, f"location {where} is outside the places you named"


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
    ok, why = _location_ok(posting, interests, profile)
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

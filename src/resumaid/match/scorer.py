"""Dimension scoring.

Every subscore carries the evidence string that produced it. That is not decoration: an
unexplained score trains the user to rubber-stamp the queue, and the human-in-the-loop is what
constraint 1 depends on.

Deterministic (ADR 0006). Where synonymy matters, it is handled with explicit token expansion
rather than an opaque model, so a surprising score can always be traced to a reason.
"""

from __future__ import annotations

import re

from resumaid import geo
from resumaid.match.gate import posting_seniority
from resumaid.models import (
    DimensionScore,
    Interests,
    Profile,
    RawPosting,
    RoleFamily,
    ScoreBreakdown,
)

_WORD = re.compile(r"[a-z0-9][a-z0-9+#.]*")

#: Token equivalences that pure lexical overlap misses. Deliberately about the *vocabulary of
#: work*, not about any employer or role family — the tool stays profile-agnostic.
_SYNONYMS: dict[str, set[str]] = {
    "js": {"javascript"}, "javascript": {"js"},
    "ts": {"typescript"}, "typescript": {"ts"},
    "py": {"python"}, "python": {"py"},
    "golang": {"go"}, "go": {"golang"},
    "c++": {"cpp"}, "cpp": {"c++"},
    "c#": {"csharp"}, "csharp": {"c#"},
    "k8s": {"kubernetes"}, "kubernetes": {"k8s"},
    "ml": {"machine", "learning"}, "ai": {"artificial", "intelligence"},
    "nlp": {"language"}, "cv": {"vision"},
    "postgres": {"postgresql"}, "postgresql": {"postgres"},
    "aws": {"amazon"}, "gcp": {"google"},
    "ci": {"cicd"}, "cd": {"cicd"},
    "sw": {"software"}, "hw": {"hardware"},
    "embedded": {"firmware"}, "firmware": {"embedded"},
}

_SENIORITY_DISTANCE = ["intern", "new-grad", "junior", "senior"]


def tokens(text: str) -> set[str]:
    # The trailing-dot strip matters: the character class keeps '.' so ".net" and "node.js"
    # survive, which otherwise makes "Python." at the end of a sentence a different token
    # from "python".
    return {t.rstrip(".") for t in _WORD.findall((text or "").lower()) if t.rstrip(".")}


def expand(toks: set[str]) -> set[str]:
    out = set(toks)
    for t in toks:
        out |= _SYNONYMS.get(t, set())
    return out


def _overlap(a: set[str], b: set[str]) -> set[str]:
    return expand(a) & expand(b)


def score_skills(posting: RawPosting, profile: Profile) -> DimensionScore:
    """How much of the user's skill set the posting actually asks for."""
    skill_tokens = {s.lower().strip() for s in profile.skills if s.strip()}
    if not skill_tokens:
        return DimensionScore(name="skills", score=50.0, weight=3.0,
                              evidence="no skills parsed from your resumes; scored neutral")
    hay = tokens(f"{posting.title}\n{posting.description_text or ''}")
    hits = sorted({s for s in skill_tokens if expand(tokens(s)) & expand(hay)})
    if not hits:
        return DimensionScore(name="skills", score=15.0, weight=3.0,
                              evidence="none of your listed skills appear in the posting")
    # Saturating: matching 8 of your skills is a strong signal; 20 is not 2.5x stronger.
    ratio = min(1.0, len(hits) / 8.0)
    score = 30.0 + 70.0 * ratio
    shown = ", ".join(hits[:8])
    # "only" when the overlap is thin, so the sentence reads as the deficit it is when this
    # dimension turns up in the missing-signals list.
    qualifier = "only " if len(hits) <= 2 else ""
    verb = "appears" if len(hits) == 1 else "appear"
    return DimensionScore(
        name="skills", score=score, weight=3.0,
        evidence=f"{qualifier}{len(hits)} of your skills {verb}: {shown}",
    )


def match_family(posting: RawPosting, interests: Interests) -> tuple[RoleFamily | None, float, str]:
    """Which declared role family this posting belongs to, and how strongly."""
    hay = tokens(
        f"{posting.title} {posting.department or ''} {posting.description_text or ''}"
    )
    title_toks = tokens(posting.title)
    best: tuple[RoleFamily | None, float, str] = (None, 0.0, "no declared family matched")
    for fam in interests.role_families:
        kws = [k for k in [*fam.keywords, fam.name] if k]
        if not kws:
            continue
        hits, title_hits = [], []
        for kw in kws:
            kw_toks = tokens(kw)
            if not kw_toks:
                continue
            if kw_toks <= expand(hay):
                hits.append(kw)
                if kw_toks <= expand(title_toks):
                    title_hits.append(kw)
        if not hits:
            continue
        # A keyword in the title means far more than one buried in the body.
        raw = min(1.0, (len(hits) + 2 * len(title_hits)) / max(3.0, len(kws)))
        weighted = raw * fam.weight
        if weighted > best[1]:
            where = (
                f"title matches {', '.join(title_hits)}" if title_hits
                else f"mentions {', '.join(hits[:4])}"
            )
            best = (fam, weighted, f"{fam.name}: {where}")
    return best


def score_role_family(
    posting: RawPosting, interests: Interests
) -> tuple[DimensionScore, str | None]:
    if not interests.role_families:
        return (
            DimensionScore(name="role_family", score=50.0, weight=3.0,
                           evidence="no role families declared; scored neutral"),
            None,
        )
    fam, strength, why = match_family(posting, interests)
    if fam is None:
        return (
            DimensionScore(name="role_family", score=10.0, weight=3.0,
                           evidence="matches none of your declared role families"),
            None,
        )
    return (
        DimensionScore(name="role_family", score=min(100.0, 25.0 + 75.0 * strength),
                       weight=3.0, evidence=why),
        fam.name,
    )


def score_seniority(posting: RawPosting, profile: Profile, interests: Interests) -> DimensionScore:
    wanted = [s.lower() for s in interests.hard_filters.seniority] or (
        [profile.seniority] if profile.seniority else []
    )
    level = posting_seniority(posting)
    if not wanted or not level:
        return DimensionScore(name="seniority", score=60.0, weight=1.5,
                              evidence=f"posting reads {level or 'unspecified'};"
                                       " nothing to compare")
    if level in wanted:
        return DimensionScore(name="seniority", score=100.0, weight=1.5,
                              evidence=f"posting reads {level}, which you're targeting")
    try:
        gap = min(abs(_SENIORITY_DISTANCE.index(level) - _SENIORITY_DISTANCE.index(w))
                  for w in wanted if w in _SENIORITY_DISTANCE)
    except ValueError:
        gap = 2
    return DimensionScore(
        name="seniority", score=max(0.0, 80.0 - 35.0 * gap), weight=1.5,
        evidence=f"posting reads {level}; you're targeting {', '.join(wanted)}",
    )


#: Score for a role in a place you named explicitly, before its weight is applied.
NAMED_PLACE_SCORE = 100.0
#: A state you named is a weaker signal than the city itself.
NAMED_STATE_SCORE = 88.0
#: A role at your doorstep, decaying to this at the edge of your radius.
AT_HOME_SCORE = 100.0
EDGE_OF_RADIUS_SCORE = 82.0
#: Beyond the radius, how much a role is worth depends on whether you'd move for it.
RELOCATION_CEILING = {"preferred": 75.0, "willing": 55.0, "no": 20.0}


def home_location(profile: Profile, interests: Interests) -> str | None:
    """Where the user is. Declared preference wins; otherwise the resume's own location."""
    return interests.locations.home or (profile.locations[0] if profile.locations else None)


def score_location(
    posting: RawPosting, interests: Interests, profile: Profile | None = None
) -> DimensionScore:
    """How well a posting's location suits the user.

    Three signals, best-of: a place you named explicitly, a state you named, and how far the
    role is from home. Each carries the weight you gave it, so "Denver at 0.7" ranks below
    "Boston at 1.0" without either being excluded.
    """
    prefs = interests.locations
    if posting.remote and prefs.remote:
        return DimensionScore(name="location", score=100.0, weight=2.0, evidence="remote")

    shown = ", ".join(posting.locations) or "unspecified"
    best: tuple[float, str] | None = None

    def consider(score: float, evidence: str) -> None:
        nonlocal best
        if best is None or score > best[0]:
            best = (score, evidence)

    posting_states = {geo.state_of(loc) for loc in posting.locations} - {None}

    for pref in prefs.all_places():
        if pref.place:
            wanted = geo.resolve(pref.place)
            for loc in posting.locations:
                here = geo.resolve(loc)
                pref_city = geo.parse_place(pref.place)[0]
                loc_city = geo.parse_place(loc)[0]
                same = (wanted is not None and wanted == here) or (
                    pref_city is not None and pref_city == loc_city
                )
                if same:
                    consider(
                        NAMED_PLACE_SCORE * pref.weight,
                        f"in {pref.place}, which you named"
                        + ("" if pref.weight >= 1.0 else f" (weight {pref.weight:g})"),
                    )
        elif pref.state and pref.state.upper() in posting_states:
            consider(
                NAMED_STATE_SCORE * pref.weight,
                f"in {pref.state.upper()}, a state you named"
                + ("" if pref.weight >= 1.0 else f" (weight {pref.weight:g})"),
            )

    # Proximity to home, which is what makes "just over the state line" score like the
    # short commute it is rather than like another state.
    home = home_location(profile or Profile(), interests)
    radius = prefs.max_distance_miles
    if home and radius:
        for loc in posting.locations:
            miles = geo.distance_between(home, loc)
            if miles is None:
                continue
            if miles <= radius:
                fraction = miles / radius if radius else 0.0
                consider(
                    AT_HOME_SCORE - (AT_HOME_SCORE - EDGE_OF_RADIUS_SCORE) * fraction,
                    f"{miles:.0f}mi from {home}, inside your {radius:.0f}mi radius",
                )
            else:
                ceiling = RELOCATION_CEILING.get(prefs.relocation, 20.0)
                # Decay from the edge of the radius toward the relocation ceiling, so 80 miles
                # away still beats 800 when you would consider moving.
                overshoot = min(1.0, (miles - radius) / (radius * 8))
                consider(
                    EDGE_OF_RADIUS_SCORE
                    - (EDGE_OF_RADIUS_SCORE - ceiling) * (0.35 + 0.65 * overshoot),
                    f"{miles:.0f}mi from {home}"
                    + (
                        f"; you'd {'prefer to ' if prefs.relocation == 'preferred' else ''}relocate"
                        if prefs.will_relocate
                        else "; outside your radius"
                    ),
                )

    if best is not None:
        return DimensionScore(name="location", score=min(100.0, best[0]), weight=2.0,
                              evidence=best[1])

    # Nothing resolved: fall back to willingness alone, and say so rather than implying more.
    if prefs.relocation == "preferred":
        return DimensionScore(name="location", score=75.0, weight=2.0,
                              evidence=f"{shown}; you'd prefer to relocate")
    if prefs.relocation == "willing":
        return DimensionScore(name="location", score=55.0, weight=2.0,
                              evidence=f"{shown}; you'd relocate for the right role")
    return DimensionScore(name="location", score=25.0, weight=2.0,
                          evidence=f"{shown}, outside your declared locations")


def score_industry(posting: RawPosting, interests: Interests) -> DimensionScore:
    if not interests.industries:
        return DimensionScore(name="industry", score=50.0, weight=1.0,
                              evidence="no industries declared; scored neutral")
    hay = tokens(
        f"{posting.company} {posting.department or ''} {posting.description_text or ''}"
    )
    hits = [i for i in interests.industries if tokens(i) <= expand(hay)]
    if hits:
        return DimensionScore(name="industry", score=100.0, weight=1.0,
                              evidence=f"matches {', '.join(hits)}")
    return DimensionScore(name="industry", score=35.0, weight=1.0,
                          evidence="no declared industry mentioned")


def score(
    posting: RawPosting,
    profile: Profile,
    interests: Interests,
    hard_filter_results: dict[str, str] | None = None,
) -> ScoreBreakdown:
    family_dim, family_name = score_role_family(posting, interests)
    dims = [
        family_dim,
        score_skills(posting, profile),
        score_seniority(posting, profile, interests),
        score_location(posting, interests, profile),
        score_industry(posting, interests),
    ]
    matched = [d.evidence for d in dims if d.score >= 70]
    # Name the dimension and its score in the missing list: the evidence string alone is
    # phrased as a statement of fact, which reads oddly under a "what's missing" heading.
    missing = [
        f"{d.name.replace('_', ' ')} ({d.score:.0f}/100) — {d.evidence}"
        for d in dims
        if d.score < 40
    ]
    if posting.description_text is None:
        missing.append("no description available — scored on title and company alone")
    return ScoreBreakdown(
        dimensions=dims,
        matched_signals=matched,
        missing_signals=missing,
        hard_filter_results=hard_filter_results or {},
        role_family=family_name,
    )

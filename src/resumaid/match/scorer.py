"""Dimension scoring.

Every subscore carries the evidence string that produced it. That is not decoration: an
unexplained score trains the user to rubber-stamp the queue, and the human-in-the-loop is what
constraint 1 depends on.

Deterministic (ADR 0006). Where synonymy matters, it is handled with explicit token expansion
rather than an opaque model, so a surprising score can always be traced to a reason.
"""

from __future__ import annotations

import re

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
    return DimensionScore(
        name="skills", score=score, weight=3.0,
        evidence=f"{len(hits)} of your skills appear: {shown}",
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


def score_location(posting: RawPosting, interests: Interests) -> DimensionScore:
    prefs = interests.locations
    if posting.remote and prefs.remote:
        return DimensionScore(name="location", score=100.0, weight=2.0, evidence="remote")
    locs = ", ".join(posting.locations) or "unspecified"
    for metro in prefs.metros:
        m = metro.lower()
        if any(m.split(",")[0].strip() in loc.lower() for loc in posting.locations):
            return DimensionScore(name="location", score=100.0, weight=2.0,
                                  evidence=f"in {metro}, a metro you named")
    if prefs.relocation == "preferred":
        return DimensionScore(name="location", score=75.0, weight=2.0,
                              evidence=f"{locs}; you'd prefer to relocate")
    if prefs.relocation == "willing":
        return DimensionScore(name="location", score=55.0, weight=2.0,
                              evidence=f"{locs}; you'd relocate for the right role")
    return DimensionScore(name="location", score=25.0, weight=2.0,
                          evidence=f"{locs}, outside your declared locations")


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
        score_location(posting, interests),
        score_industry(posting, interests),
    ]
    matched = [d.evidence for d in dims if d.score >= 70]
    missing = [d.evidence for d in dims if d.score < 40]
    if posting.description_text is None:
        missing.append("no description available — scored on title and company alone")
    return ScoreBreakdown(
        dimensions=dims,
        matched_signals=matched,
        missing_signals=missing,
        hard_filter_results=hard_filter_results or {},
        role_family=family_name,
    )

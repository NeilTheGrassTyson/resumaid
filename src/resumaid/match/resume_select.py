"""Choosing which of the user's resumes to send.

The MVP *selects among documents the user wrote*. It never rewrites, merges, or generates one —
that is a later phase, and nothing here anticipates it (ADR 0005).

Matching asks "am I a fit for this role?" and is answered from the union profile. Selection asks
"which of my documents argues that best?" and is answered from each document's emphasis. They
are different questions, and conflating them would mean scoring every resume against every
posting for no gain.
"""

from __future__ import annotations

from dataclasses import dataclass

from resumaid.match.scorer import expand, tokens
from resumaid.models import RawPosting, ResumeDoc


@dataclass
class Selection:
    resume_id: int | None
    rationale: str
    runner_up_id: int | None = None


def select(posting: RawPosting, resumes: list[ResumeDoc]) -> Selection:
    if not resumes:
        return Selection(None, "no resumes uploaded yet")
    if len(resumes) == 1:
        only = resumes[0]
        return Selection(only.id, f"{only.filename} is your only uploaded resume")

    hay = expand(
        tokens(f"{posting.title} {posting.department or ''} {posting.description_text or ''}")
    )
    scored: list[tuple[float, list[str], ResumeDoc]] = []
    for doc in resumes:
        terms = [t for t in doc.emphasis_terms if t in hay]
        # Score by *concentration*, not raw count: what share of this document's emphasis is
        # about this posting. A raw count rewards breadth, which hands every role to the master
        # resume — it covers everything, so it matches more of everything.
        share = len(terms) / len(doc.emphasis_terms) if doc.emphasis_terms else 0.0
        # And the master is still the fallback rather than the pick, even on a tie.
        penalty = 0.85 if doc.is_master else 1.0
        scored.append((share * penalty, terms, doc))
    scored.sort(key=lambda t: -t[0])

    best_score, best_terms, best = scored[0]
    runner = scored[1][2] if len(scored) > 1 else None

    if best_score == 0:
        master = next((d for d in resumes if d.is_master), resumes[0])
        return Selection(
            master.id,
            f"no resume's emphasis matched this posting; defaulting to {master.filename}",
            runner_up_id=runner.id if runner and runner.id != master.id else None,
        )
    shown = ", ".join(best_terms[:5])
    return Selection(
        best.id,
        f"{best.filename} emphasizes {shown} — the strongest overlap with this posting",
        runner_up_id=runner.id if runner else None,
    )

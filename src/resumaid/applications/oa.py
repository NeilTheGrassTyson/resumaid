"""Anticipating an online assessment.

Three signals, in descending weight: the user's own recorded history, deterministic phrase
extraction over the posting text, and (opt-in) cached company research.

Deliberately absent: any hardcoded company-to-OA table. CLAUDE.md forbids hardcoding employers,
the tool is profile-agnostic, and a stale table is worse than no prediction (ADR 0008).
"""

from __future__ import annotations

import re
import sqlite3

from resumaid.applications.store import oa_history
from resumaid.models import Confidence, OAAssessment, OAEvidence, OAExpectation
from resumaid.util import norm_company

#: Phrases that indicate an assessment. Generic hiring-process vocabulary and the names of
#: assessment platforms — not employers. Weight is how strongly each implies one.
_PHRASES: list[tuple[str, float]] = [
    (r"online assessment", 1.0),
    (r"\bOA\b", 0.5),
    (r"coding (?:assessment|challenge|test|exercise)", 1.0),
    (r"technical (?:assessment|screen(?:ing)?|challenge|exercise)", 0.9),
    (r"take[- ]home (?:assignment|project|test|exercise)", 1.0),
    (r"skills? (?:assessment|test)", 0.8),
    (r"timed (?:challenge|assessment|test)", 1.0),
    (r"pre[- ]employment (?:test|assessment|screening)", 0.8),
    (r"work sample", 0.6),
    (r"aptitude test", 0.8),
    (r"hackerrank", 1.0),
    (r"codesignal", 1.0),
    (r"codility", 1.0),
    (r"\bkarat\b", 0.9),
    (r"leetcode[- ]style", 0.8),
    (r"hirevue", 0.8),
    (r"woven", 0.5),
    (r"triplebyte", 0.7),
]

#: Phrases that point the other way.
_NEGATIVE: list[tuple[str, float]] = [
    (r"no (?:coding )?(?:test|assessment)s?\b", 1.0),
    (r"we do(?:n't| not) (?:do|use) (?:take[- ]homes?|coding tests?)", 1.0),
    (r"conversation[- ]based interview", 0.6),
]

_COMPILED = [(re.compile(p, re.I), w) for p, w in _PHRASES]
_COMPILED_NEG = [(re.compile(p, re.I), w) for p, w in _NEGATIVE]

_SENTENCE = re.compile(r"[^.!?\n]*[.!?\n]|[^.!?\n]+$")


def _quote_for(text: str, match: re.Match[str]) -> str:
    """The sentence a hit appeared in, so the evidence is auditable rather than oracular."""
    for m in _SENTENCE.finditer(text):
        if m.start() <= match.start() < m.end():
            return m.group(0).strip()[:300]
    start = max(0, match.start() - 80)
    return text[start : match.end() + 80].strip()


def scan_posting_text(text: str | None) -> tuple[float, list[OAEvidence]]:
    """Deterministic phrase extraction. Returns a signal score and quoted evidence."""
    if not text:
        return 0.0, []
    score = 0.0
    evidence: list[OAEvidence] = []

    # Negations first, and they mask their own span. "No coding tests" contains the positive
    # phrase "coding test"; scanning positives over the raw text would cancel the negation out.
    masked = list(text)
    for pattern, weight in _COMPILED_NEG:
        for m in pattern.finditer(text):
            score -= weight
            evidence.append(
                OAEvidence(kind="posting_text", detail=f"suggests no assessment: {m.group(0)!r}",
                           quote=_quote_for(text, m))
            )
            for i in range(m.start(), m.end()):
                masked[i] = " "
    masked_text = "".join(masked)

    seen: set[str] = set()
    for pattern, weight in _COMPILED:
        m = pattern.search(masked_text)
        if m and m.group(0).lower() not in seen:
            seen.add(m.group(0).lower())
            score += weight
            evidence.append(
                OAEvidence(kind="posting_text", detail=f"mentions {m.group(0)!r}",
                           quote=_quote_for(text, m))
            )
    return score, evidence


def assess(
    conn: sqlite3.Connection,
    *,
    company: str,
    description_text: str | None,
    use_research: bool = False,
) -> OAAssessment:
    """Predict whether this role will involve an online assessment."""
    evidence: list[OAEvidence] = []

    # 1. The user's own history — the strongest available signal, and it is theirs.
    history = oa_history(conn, company)
    got = [h for h in history if h["oa_received"]]
    none = [h for h in history if not h["oa_received"]]
    if got:
        platforms = sorted({h["oa_platform"] for h in got if h["oa_platform"]})
        detail = f"you recorded an assessment from {company} {len(got)}x"
        if platforms:
            detail += f" (via {', '.join(platforms)})"
        evidence.append(OAEvidence(kind="history", detail=detail))
        return OAAssessment(
            expected=OAExpectation.LIKELY,
            confidence=Confidence.HIGH if len(got) > 1 else Confidence.MEDIUM,
            evidence=evidence + scan_posting_text(description_text)[1],
        )
    if none:
        evidence.append(
            OAEvidence(kind="history",
                       detail=f"{len(none)} past application(s) to {company} with no assessment")
        )

    # 2. The posting text.
    text_score, text_evidence = scan_posting_text(description_text)
    evidence.extend(text_evidence)

    # 3. Optional cached company research (Sonar). Opt-in per run.
    if use_research:
        row = conn.execute(
            "SELECT oa_verdict, summary FROM company_research WHERE company_norm = ?",
            (norm_company(company),),
        ).fetchone()
        if row and row["oa_verdict"]:
            evidence.append(
                OAEvidence(kind="research", detail=row["oa_verdict"], quote=row["summary"])
            )
            if row["oa_verdict"] == "likely":
                text_score += 0.8
            elif row["oa_verdict"] == "unlikely":
                text_score -= 0.8

    if description_text is None:
        # A link-only entry gives nothing to read. Say so rather than guessing.
        return OAAssessment(
            expected=OAExpectation.UNKNOWN,
            confidence=Confidence.LOW,
            evidence=evidence
            + [OAEvidence(kind="posting_text", detail="no description available to scan")],
        )

    if text_score >= 1.0:
        expected, conf = OAExpectation.LIKELY, Confidence.MEDIUM
    elif text_score >= 0.5:
        expected, conf = OAExpectation.POSSIBLE, Confidence.LOW
    elif text_score <= -0.5 or none:
        expected, conf = OAExpectation.UNLIKELY, Confidence.LOW
    else:
        expected, conf = OAExpectation.UNKNOWN, Confidence.LOW
    return OAAssessment(expected=expected, confidence=conf, evidence=evidence)

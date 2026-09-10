"""LLM adjudication for entries near the fit floor (ADR 0006).

Confined to the cases where judgment changes an outcome. What leaves the machine is the posting
text plus a skills/education summary — never a resume file, never contact details. The payload
is asserted before it is sent (constraint 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from resumaid.models import Profile, RawPosting

#: Patterns that must never appear in an outbound payload.
_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "email address"),
    (re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b"), "phone number"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "government id"),
]


class PayloadRefused(ValueError):
    """The outbound payload contained something constraint 4 says stays on the machine."""


def assert_no_pii(payload: str) -> None:
    for pattern, label in _PII:
        if pattern.search(payload):
            raise PayloadRefused(
                f"refusing to send a payload containing a {label}. "
                "See CLAUDE.md constraint 4: data stays local."
            )


def build_payload(posting: RawPosting, profile: Profile) -> str:
    """A summary, not a resume. Skills and degree level only — no employers, no dates, no name."""
    skills = ", ".join(profile.skills[:40]) or "unspecified"
    degree = profile.highest_degree_level or "unspecified"
    seniority = profile.seniority or "unspecified"
    body = (posting.description_text or "")[:6000]
    payload = (
        f"Candidate skills: {skills}\n"
        f"Highest degree: {degree}\nTarget seniority: {seniority}\n\n"
        f"Role: {posting.title} at {posting.company}\n"
        f"Location: {', '.join(posting.locations) or 'unspecified'}\n\n"
        f"Posting:\n{body}"
    )
    assert_no_pii(payload)
    return payload


@dataclass
class Adjudication:
    verdict: str  # "above" | "below" | "unchanged"
    reason: str
    adjustment: float = 0.0


def adjudicate(
    posting: RawPosting,
    profile: Profile,
    api_key: str | None,
) -> Adjudication | None:
    """Ask for a judgment on a near-the-bar role.

    Returns None when no API key is configured — scoring must work with the LLM disabled, so
    near-the-bar entries fall back to their deterministic score and are flagged rather than
    failing the run.
    """
    if not api_key:
        return None
    payload = build_payload(posting, profile)
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=200,
            system=(
                "You judge whether a job posting is a genuine fit for a candidate, given only "
                "their skills and degree level. Answer in the form 'VERDICT: above|below|"
                "unchanged' on the first line, then one sentence of reasoning. 'above' means "
                "the deterministic score understates the fit; 'below' means it overstates it."
            ),
            messages=[{"role": "user", "content": payload}],
        )
        text = "".join(block.text for block in message.content if block.type == "text").strip()
    except Exception:
        # An adjudication failure must never take the run down; the deterministic score stands.
        return None

    first, _, rest = text.partition("\n")
    verdict = "unchanged"
    for candidate in ("above", "below", "unchanged"):
        if candidate in first.lower():
            verdict = candidate
            break
    adjustment = {"above": 6.0, "below": -6.0, "unchanged": 0.0}[verdict]
    return Adjudication(
        verdict=verdict, reason=rest.strip() or first.strip(), adjustment=adjustment
    )

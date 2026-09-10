"""The constraint-4 guard on outbound LLM payloads.

`match/llm.py` is the one place this tool sends anything about the user off the machine. What
may leave is a skills-and-degree summary plus the posting; what may not is a resume file or any
contact detail. These tests exist so that guarantee fails loudly rather than silently.
"""

from __future__ import annotations

import pytest

from resumaid.match.llm import (
    Adjudication,
    PayloadRefused,
    adjudicate,
    assert_no_pii,
    build_payload,
)
from resumaid.models import Completeness, Profile, RawPosting, Source


def _posting(**kw) -> RawPosting:
    base = dict(
        source=Source.GREENHOUSE,
        source_job_id="1",
        company="Acme Robotics",
        title="Software Engineer",
        locations=["Boston, MA"],
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
        description_text="Build flight software in C++ and Python.",
        completeness=Completeness.FULL,
    )
    base.update(kw)
    return RawPosting(**base)


PROFILE = Profile(
    name="Jane Q Public",
    skills=["Python", "C++", "Kubernetes"],
    highest_degree_level="bachelors",
    seniority="new-grad",
)


# --- assert_no_pii -------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        "reach me at jane@example.com",
        "Jane Public <jane.q.public+jobs@sub.example.co.uk>",
        "call 617-555-0134",
        "phone: (617) 555-0134",
        "+1 617.555.0134",
        "ssn 123-45-6789",
    ],
)
def test_pii_is_refused(payload):
    with pytest.raises(PayloadRefused):
        assert_no_pii(payload)


def test_refusal_names_what_it_found_and_why():
    """The error has to be actionable — and point at the rule, not just fail."""
    with pytest.raises(PayloadRefused, match="email address"):
        assert_no_pii("jane@example.com")
    with pytest.raises(PayloadRefused, match="constraint 4"):
        assert_no_pii("jane@example.com")


@pytest.mark.parametrize(
    "payload",
    [
        "Build flight software in C++ and Python.",
        "Salary 120,000-165,000 for the 2026 cohort",
        "Version 3.11.15 of the runtime",
        "",
    ],
)
def test_clean_payloads_pass(payload):
    assert_no_pii(payload)


# --- build_payload -------------------------------------------------------------------


def test_payload_excludes_the_candidates_name():
    """A name is not needed to judge fit, so it does not go."""
    payload = build_payload(_posting(), PROFILE)
    assert "Jane" not in payload
    assert "Public" not in payload


def test_payload_carries_what_the_judgment_actually_needs():
    payload = build_payload(_posting(), PROFILE)
    assert "Python" in payload and "C++" in payload
    assert "bachelors" in payload
    assert "Software Engineer" in payload
    assert "flight software" in payload


def test_payload_refuses_a_posting_containing_contact_details():
    """The posting is untrusted text too — a recruiter's email in the body must not slip out."""
    posting = _posting(description_text="Great role. Questions? recruiter@acme.example.com")
    with pytest.raises(PayloadRefused):
        build_payload(posting, PROFILE)


def test_payload_refuses_a_profile_carrying_a_phone_number():
    """Skills are user-editable free text in profile.yaml; the guard covers that path too."""
    leaky = Profile(skills=["Python", "call me on 617-555-0134"], highest_degree_level="bachelors")
    with pytest.raises(PayloadRefused):
        build_payload(_posting(), leaky)


def test_long_postings_are_truncated():
    payload = build_payload(_posting(description_text="x" * 20_000), PROFILE)
    assert len(payload) < 7_000


def test_payload_handles_an_empty_profile():
    payload = build_payload(_posting(), Profile())
    assert "unspecified" in payload


# --- adjudicate ----------------------------------------------------------------------


def test_adjudicate_is_a_no_op_without_a_key():
    """Scoring must work with the LLM disabled (ADR 0006): no key means fall back, not fail."""
    assert adjudicate(_posting(), PROFILE, None) is None
    assert adjudicate(_posting(), PROFILE, "") is None


def test_adjudicate_refuses_before_any_network_call():
    """The PII check runs ahead of the request, so a leaky payload never reaches the wire.

    `adjudicate` builds and checks the payload before it even imports the client, so this
    raising — rather than returning None the way a missing dependency would — is what proves
    the guard fires first.
    """
    posting = _posting(description_text="mail recruiter@acme.example.com")
    with pytest.raises(PayloadRefused):
        adjudicate(posting, PROFILE, "sk-test-key-not-used")


def test_adjudication_adjustments_are_bounded_and_signed():
    """'above' lifts, 'below' lowers, 'unchanged' does nothing — and none of them is large."""
    assert Adjudication("above", "r", 6.0).adjustment > 0
    assert Adjudication("below", "r", -6.0).adjustment < 0
    assert Adjudication("unchanged", "r").adjustment == 0.0

"""Adapter tests against recorded payloads, and the permitted-source allowlist.

No live calls in the default suite: a source adapter that only works when the network is up
cannot be debugged when it breaks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resumaid.models import Completeness, DatePrecision, Source
from resumaid.sources import adzuna, ashby, greenhouse, lever, usajobs
from resumaid.sources.base import ALLOWED_HOSTS, DisallowedSource, check_host
from resumaid.sources.registry import board_from_url, list_boards, register, register_from_postings

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


# --- the allowlist -------------------------------------------------------------------
# Constraint 3 is enforced in code, not just documented.


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/12345",
        "https://www.linkedin.com/jobs/view/12345",
        "https://www.indeed.com/viewjob?jk=abc",
        "https://www.glassdoor.com/job-listing/123",
        "https://careers.example.com/jobs/1",
    ],
)
def test_disallowed_hosts_are_refused(url):
    with pytest.raises(DisallowedSource):
        check_host(url)


def test_workday_is_not_on_the_allowlist():
    """CLAUDE.md leaves Workday an open question; until it is decided, it is disallowed."""
    assert not any("workday" in host for host in ALLOWED_HOSTS)


@pytest.mark.parametrize(
    "url",
    [
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
        "https://api.lever.co/v0/postings/acme?mode=json",
        "https://api.ashbyhq.com/posting-api/job-board/acme",
        "https://api.adzuna.com/v1/api/jobs/us/search/1",
        "https://data.usajobs.gov/api/search",
    ],
)
def test_permitted_hosts_pass(url):
    check_host(url)


# --- Greenhouse ----------------------------------------------------------------------


def test_greenhouse_parses_full_postings():
    postings = greenhouse.parse(load("greenhouse_board.json"), "acmerobotics", "Acme Robotics")
    assert len(postings) == 2
    first = postings[0]
    assert first.source is Source.GREENHOUSE
    assert first.title == "Software Engineer, Flight Autonomy"
    assert first.company == "Acme Robotics"
    assert first.completeness is Completeness.FULL
    assert "C++" in first.description_text
    assert "<p>" not in first.description_text  # HTML stripped
    assert first.apply_url.startswith("https://boards.greenhouse.io/")


def test_greenhouse_date_is_approximate_not_exact():
    """Greenhouse exposes updated_at, not a creation date. Calling it exact would let an
    edited old posting masquerade as fresh."""
    postings = greenhouse.parse(load("greenhouse_board.json"), "acmerobotics")
    assert postings[0].posted_at_precision is DatePrecision.APPROXIMATE


def test_greenhouse_empty_content_becomes_link_only():
    postings = greenhouse.parse(load("greenhouse_board.json"), "acmerobotics")
    assert postings[1].completeness is Completeness.LINK_ONLY
    assert postings[1].remote is True  # "Remote - US"


# --- Lever ---------------------------------------------------------------------------


def test_lever_parses_and_dates_are_exact():
    postings = lever.parse(load("lever_postings.json"), "scaleco", "ScaleCo")
    assert len(postings) == 2
    assert postings[0].posted_at_precision is DatePrecision.EXACT
    assert postings[0].posted_at is not None
    assert postings[0].employment_type == "Full-time"
    assert postings[0].department == "Platform"


def test_lever_reads_remote_from_workplace_type():
    postings = lever.parse(load("lever_postings.json"), "scaleco")
    assert postings[0].remote is False
    assert postings[1].remote is True


# --- Ashby ---------------------------------------------------------------------------


def test_ashby_parses_locations_and_compensation():
    postings = ashby.parse(load("ashby_board.json"), "vectorlabs")
    assert postings[0].company == "Vector Labs"
    assert postings[0].locations == ["San Francisco, CA", "Remote - US"]
    assert postings[0].compensation == "$180K – $220K"
    assert postings[0].posted_at_precision is DatePrecision.EXACT


def test_ashby_falls_back_to_html_description():
    postings = ashby.parse(load("ashby_board.json"), "vectorlabs")
    assert "Markdown" in postings[1].description_text
    assert "<b>" not in postings[1].description_text
    # No publishedAt on this one, only updatedAt.
    assert postings[1].posted_at_precision is DatePrecision.APPROXIMATE


# --- Adzuna --------------------------------------------------------------------------


def test_adzuna_snippets_are_partial_not_full():
    """A two-line teaser is not a description; scoring it as one would overstate confidence."""
    postings = adzuna.parse(load("adzuna_search.json"))
    assert all(p.completeness is Completeness.PARTIAL for p in postings)
    assert all(p.confidence.value == "medium" for p in postings)


def test_adzuna_carries_a_provenance_note():
    postings = adzuna.parse(load("adzuna_search.json"))
    assert "Adzuna" in postings[0].provenance_note
    assert "paste" in postings[0].provenance_note.lower()


def test_adzuna_parses_salary_range():
    postings = adzuna.parse(load("adzuna_search.json"))
    assert postings[0].compensation == "120,000–165,000"
    assert postings[1].compensation is None


# --- USAJobs -------------------------------------------------------------------------


def test_usajobs_parses_a_full_federal_posting():
    postings = usajobs.parse(load("usajobs_search.json"))
    assert len(postings) == 1
    job = postings[0]
    assert job.source is Source.USAJOBS
    assert job.company == "Air Force Research Laboratory"
    assert job.completeness is Completeness.FULL
    assert "autonomy" in job.description_text.lower()
    assert "Develop algorithms." in job.description_text
    assert job.closes_at is not None
    assert job.apply_url.endswith("/apply")


# --- the self-feeding registry -------------------------------------------------------


@pytest.mark.parametrize(
    "url,source,token",
    [
        ("https://boards.greenhouse.io/anduril/jobs/4567", Source.GREENHOUSE, "anduril"),
        ("https://job-boards.greenhouse.io/acme/jobs/1", Source.GREENHOUSE, "acme"),
        ("https://jobs.lever.co/scaleai/abc-123", Source.LEVER, "scaleai"),
        ("https://jobs.ashbyhq.com/openai/some-uuid", Source.ASHBY, "openai"),
    ],
)
def test_board_tokens_are_recognized(url, source, token):
    ref = board_from_url(url)
    assert ref is not None
    assert ref.source is source and ref.token == token


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.wd1.myworkdayjobs.com/careers/job/123",
        "https://www.linkedin.com/jobs/view/123",
        "https://careers.acme.com/openings/5",
        "",
    ],
)
def test_non_ats_urls_yield_no_board(url):
    assert board_from_url(url) is None


def test_aggregator_results_grow_the_registry(db):
    """An Adzuna hit whose apply URL is a Greenhouse board becomes a direct source."""
    postings = adzuna.parse(load("adzuna_search.json"))
    added = register_from_postings(db, postings)
    assert added == 1
    boards = list_boards(db)
    assert [(b["source"], b["token"]) for b in boards] == [("greenhouse", "heliosystems")]
    assert boards[0]["discovered_via"] == "adzuna"


def test_registering_the_same_board_twice_is_idempotent(db):
    assert register(db, Source.GREENHOUSE, "acme", company="Acme") is True
    assert register(db, Source.GREENHOUSE, "acme") is False
    assert len(list_boards(db)) == 1


# --- live smoke test (opt in) --------------------------------------------------------


@pytest.mark.live
def test_live_greenhouse_board():
    """Opt-in: `pytest -m live`. Hits one real public board to catch schema drift."""
    from resumaid.sources.base import FetchContext, make_client

    with make_client() as client:
        postings = greenhouse.fetch(FetchContext(client), "vercel")
    assert postings
    assert all(p.apply_url for p in postings)

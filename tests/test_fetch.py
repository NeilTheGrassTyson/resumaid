"""The HTTP layer: request shaping, the permitted-host allowlist, and failure isolation.

Everything here is mocked. The point is to exercise the real request path — `FetchContext.get`,
where the allowlist is actually enforced — rather than only the pure `parse()` functions the
adapter tests cover.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from resumaid import run as run_mod
from resumaid.config import Settings
from resumaid.models import Interests, LocationPrefs, RoleFamily, Source
from resumaid.sources import adzuna, ashby, greenhouse, lever, usajobs
from resumaid.sources.base import DisallowedSource, FetchContext, RateLimiter
from resumaid.sources.registry import list_boards, register

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def ctx():
    """A context with rate limiting effectively disabled, so tests don't sleep."""
    with httpx.Client() as client:
        yield FetchContext(client, RateLimiter(per_second=10_000))


# --- the allowlist, on the real request path ---------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/careers/jobs",
        "https://www.linkedin.com/jobs/search",
        "https://www.indeed.com/jobs",
        "https://careers.example.com/api/jobs",
    ],
)
def test_get_refuses_a_disallowed_host_before_issuing_a_request(ctx, url):
    """Constraint 3 is enforced in the code path every adapter goes through, not just in docs.

    respx asserts it: with no route registered, any request that escaped the guard would raise
    a connection error rather than DisallowedSource.
    """
    with respx.mock(assert_all_called=False) as mock:
        with pytest.raises(DisallowedSource):
            ctx.get(url)
        assert not mock.calls, "a request was issued to a host outside the allowlist"


def test_workday_is_refused_even_though_it_is_the_biggest_gap(ctx):
    """The open question in CLAUDE.md stays closed in code until the founder decides."""
    with pytest.raises(DisallowedSource, match="constraint 3"):
        ctx.get("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/12345")


# --- request shaping ----------------------------------------------------------------------


@respx.mock
def test_greenhouse_requests_content_and_parses(ctx):
    route = respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json=load("greenhouse_board.json"))
    )
    postings = greenhouse.fetch(ctx, "acme", "Acme Robotics")
    assert route.called
    assert "content=true" in str(route.calls[0].request.url)
    assert postings[0].company == "Acme Robotics"
    assert postings[0].source is Source.GREENHOUSE


@respx.mock
def test_lever_requests_json_mode(ctx):
    route = respx.get("https://api.lever.co/v0/postings/scaleco").mock(
        return_value=httpx.Response(200, json=load("lever_postings.json"))
    )
    postings = lever.fetch(ctx, "scaleco")
    assert "mode=json" in str(route.calls[0].request.url)
    assert len(postings) == 2


@respx.mock
def test_ashby_requests_compensation(ctx):
    route = respx.get("https://api.ashbyhq.com/posting-api/job-board/vectorlabs").mock(
        return_value=httpx.Response(200, json=load("ashby_board.json"))
    )
    postings = ashby.fetch(ctx, "vectorlabs")
    assert "includeCompensation=true" in str(route.calls[0].request.url)
    assert postings[0].compensation


@respx.mock
def test_adzuna_sends_credentials_as_query_params(ctx):
    route = respx.get(host="api.adzuna.com").mock(
        return_value=httpx.Response(200, json=load("adzuna_search.json"))
    )
    adzuna.fetch(ctx, app_id="the-id", app_key="the-key", what="flight software",
                 where="Boston, MA")
    url = route.calls[0].request.url
    assert url.params["app_id"] == "the-id"
    assert url.params["app_key"] == "the-key"
    assert url.params["what"] == "flight software"
    assert url.params["where"] == "Boston, MA"


@respx.mock
def test_usajobs_sends_its_key_and_registered_email_as_headers(ctx):
    """USAJobs identifies callers by a registered email in User-Agent; it goes nowhere else."""
    route = respx.get(host="data.usajobs.gov").mock(
        return_value=httpx.Response(200, json=load("usajobs_search.json"))
    )
    usajobs.fetch(ctx, api_key="secret-key", email="you@example.com", keyword="autonomy")
    request = route.calls[0].request
    assert request.headers["Authorization-Key"] == "secret-key"
    assert request.headers["User-Agent"] == "you@example.com"
    assert request.url.params["Keyword"] == "autonomy"


@respx.mock
def test_a_server_error_raises_for_the_caller_to_handle(ctx):
    respx.get(host="boards-api.greenhouse.io").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        greenhouse.fetch(ctx, "acme")


# --- failure isolation in a run ------------------------------------------------------------


def _interests() -> Interests:
    return Interests(
        role_families=[RoleFamily(name="software", weight=1.0, keywords=["software", "engineer"])],
        locations=LocationPrefs(remote=True, relocation="willing"),
    )


@respx.mock
def test_one_dead_board_does_not_abort_the_run(db):
    """A 404 on one company must not cost you every other company's postings."""
    register(db, Source.GREENHOUSE, "acme")
    register(db, Source.GREENHOUSE, "goneaway")
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json=load("greenhouse_board.json"))
    )
    respx.get("https://boards-api.greenhouse.io/v1/boards/goneaway/jobs").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )

    report = run_mod.RunReport()
    postings = run_mod.fetch_all(db, _interests(), Settings(secrets={}), report)

    assert len(postings) == 2  # the healthy board's jobs still arrived
    assert any("404" in err for err in report.errors)
    statuses = {b["token"]: b["last_status"] for b in list_boards(db)}
    assert statuses["acme"].startswith("ok")
    assert "404" in statuses["goneaway"]


@respx.mock
def test_a_connection_failure_is_recorded_not_raised(db):
    register(db, Source.LEVER, "scaleco")
    respx.get(host="api.lever.co").mock(side_effect=httpx.ConnectError("network down"))
    report = run_mod.RunReport()
    assert run_mod.fetch_all(db, _interests(), Settings(secrets={}), report) == []
    assert report.errors


@respx.mock
def test_aggregators_are_skipped_without_credentials(db):
    """The ATS sources need no keys, so the tool is useful before any are configured."""
    register(db, Source.GREENHOUSE, "acme")
    respx.get(host="boards-api.greenhouse.io").mock(
        return_value=httpx.Response(200, json=load("greenhouse_board.json"))
    )
    report = run_mod.RunReport()
    run_mod.fetch_all(db, _interests(), Settings(secrets={}), report)
    assert "adzuna" not in report.sources_polled
    assert "usajobs" not in report.sources_polled
    assert report.sources_polled == ["ats"]


@respx.mock
def test_aggregators_are_polled_when_credentials_exist(db):
    respx.get(host="api.adzuna.com").mock(
        return_value=httpx.Response(200, json=load("adzuna_search.json"))
    )
    settings = Settings(secrets={"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"})
    report = run_mod.RunReport()
    postings = run_mod.fetch_all(db, _interests(), settings, report)
    assert "adzuna" in report.sources_polled
    assert postings


@respx.mock
def test_search_terms_come_from_declared_interests(db):
    """Queries are built from what the user declared, never from anything baked in."""
    route = respx.get(host="api.adzuna.com").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    interests = Interests(
        role_families=[
            RoleFamily(name="aerospace", weight=1.0, keywords=["flight software", "autonomy"])
        ],
        locations=LocationPrefs(metros=["Denver, CO"]),
    )
    settings = Settings(secrets={"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"})
    run_mod.fetch_all(db, interests, settings, run_mod.RunReport())
    queried = {call.request.url.params["what"] for call in route.calls}
    assert queried == {"flight software", "autonomy"}
    assert route.calls[0].request.url.params["where"] == "Denver, CO"


def test_rate_limiter_spaces_requests_per_host():
    import time

    limiter = RateLimiter(per_second=50)
    start = time.monotonic()
    for _ in range(3):
        limiter.wait("example.com")
    assert time.monotonic() - start >= 0.03


def test_no_employer_domain_is_reachable():
    """The allowlist holds only APIs, never a company's own application endpoint."""
    from resumaid.sources.base import ALLOWED_HOSTS

    permitted = (".greenhouse.io", ".lever.co", ".ashbyhq.com", ".adzuna.com", ".usajobs.gov")
    assert all(host.endswith(permitted) for host in ALLOWED_HOSTS)

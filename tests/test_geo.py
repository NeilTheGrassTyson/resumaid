"""Offline place resolution, distance, and location scoring.

The point of the bundled place table is that "40 miles away, over a state line" scores like the
short commute it is rather than like another state. These tests pin that behavior, and the
distances are checked against known real-world values so a broken table is obvious.
"""

from __future__ import annotations

import pytest

from resumaid import geo
from resumaid.db import connect
from resumaid.ingest.resume import detect_home_location
from resumaid.match.gate import evaluate
from resumaid.match.scorer import score_location
from resumaid.models import (
    Completeness,
    HardFilters,
    Interests,
    LocationPrefs,
    PlacePref,
    Profile,
    RawPosting,
    Source,
)


def posting(*locations: str, remote: bool = False) -> RawPosting:
    return RawPosting(
        source=Source.GREENHOUSE,
        source_job_id="1",
        company="Acme",
        title="Software Engineer",
        locations=list(locations),
        remote=remote,
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
        description_text="Build software.",
        completeness=Completeness.FULL,
    )


def interests(**location_kw) -> Interests:
    return Interests(locations=LocationPrefs(**location_kw), hard_filters=HardFilters())


BOSTON = Profile(locations=["Boston, MA"], highest_degree_level="bachelors")


# --- parsing and resolution --------------------------------------------------------------


@pytest.mark.parametrize(
    "text,city,state",
    [
        ("Boston, MA", "boston", "MA"),
        ("Boston, Massachusetts", "boston", "MA"),
        ("Denver, CO (Hybrid)", "denver", "CO"),
        ("Greater Boston Area", "boston", None),
        ("San Francisco, CA", "san francisco", "CA"),
        ("Remote - US", None, None),
        ("Remote", None, None),
        ("", None, None),
    ],
)
def test_parse_place(text, city, state):
    assert geo.parse_place(text) == (city, state)


@pytest.mark.parametrize("token,code", [("MA", "MA"), ("Massachusetts", "MA"), ("ohio", "OH"),
                                        ("D.C.", None), ("Nowhere", None)])
def test_normalize_state(token, code):
    assert geo.normalize_state(token) == code


def test_resolve_known_cities():
    boston = geo.resolve("Boston, MA")
    assert boston is not None
    assert boston.state == "MA"
    assert 42.0 < boston.lat < 42.7
    assert -71.5 < boston.lon < -70.8


def test_a_city_in_the_wrong_state_does_not_resolve():
    """'Boston, CA' is a mistake, not a fuzzy match for Boston, MA."""
    assert geo.resolve("Boston, CA") is None


def test_ambiguous_bare_city_resolves_to_the_largest():
    """Someone writing 'Springfield' means the biggest one, absent other information."""
    springfield = geo.resolve("Springfield")
    assert springfield is not None
    others = [p for p in geo._table()[1] if p.city == "Springfield"]
    assert springfield.population == max(p.population for p in others)


def test_unresolvable_places_return_none_rather_than_guessing():
    assert geo.resolve("Wright-Patterson AFB, Ohio") is None
    assert geo.resolve("Remote") is None


def test_state_falls_back_when_the_city_is_unknown():
    """A place the table lacks still contributes its state."""
    assert geo.state_of("Wright-Patterson AFB, Ohio") == "OH"


# --- distance ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,expected,tolerance",
    [
        ("Boston, MA", "Providence, RI", 41, 8),
        ("Boston, MA", "Cambridge, MA", 3, 3),
        ("New York, NY", "Newark, NJ", 9, 5),
        ("San Francisco, CA", "San Jose, CA", 42, 8),
        ("Boston, MA", "Denver, CO", 1766, 60),
        ("Boston, MA", "Los Angeles, CA", 2591, 80),
    ],
)
def test_distances_match_reality(a, b, expected, tolerance):
    miles = geo.distance_between(a, b)
    assert miles is not None
    assert abs(miles - expected) <= tolerance, f"{a}->{b} came out {miles:.0f}mi"


def test_distance_is_symmetric_and_zero_to_itself():
    there = geo.distance_between("Boston, MA", "Denver, CO")
    back = geo.distance_between("Denver, CO", "Boston, MA")
    assert there == pytest.approx(back)
    assert geo.distance_between("Boston, MA", "Boston, MA") == pytest.approx(0.0, abs=0.01)


def test_distance_is_none_when_a_place_is_unknown():
    assert geo.distance_between("Boston, MA", "Atlantis") is None


# --- home location from the resume --------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Jane Public\nBoston, MA | jane@example.com | 617-555-0134\n", "Boston, MA"),
        ("Jane Public\nCambridge, Massachusetts\n", "Cambridge, MA"),
        ("Jane Public\njane@example.com  (617) 555-0134  Seattle, WA\n", "Seattle, WA"),
        # A city further down belongs to an employer, not the candidate.
        ("Jane Public\njane@x.com\n\nExperience\nAcme, Denver, CO 2024-2025\n", None),
        ("Jane Public\nNo location at all\n", None),
    ],
)
def test_home_location_is_read_from_the_contact_block(text, expected):
    assert detect_home_location(text) == expected


# --- scoring ------------------------------------------------------------------------------


def test_remote_scores_full_when_you_take_remote():
    assert score_location(posting(remote=True), interests(remote=True), BOSTON).score == 100


def test_a_named_place_scores_full():
    prefs = interests(places=[PlacePref(place="Boston, MA", weight=1.0)])
    result = score_location(posting("Boston, MA"), prefs, BOSTON)
    assert result.score == 100
    assert "you named" in result.evidence


def test_weight_scales_a_named_place():
    """Denver at 0.7 ranks below Boston at 1.0 without being excluded."""
    prefs = interests(
        places=[
            PlacePref(place="Boston, MA", weight=1.0),
            PlacePref(place="Denver, CO", weight=0.7),
        ]
    )
    boston = score_location(posting("Boston, MA"), prefs, BOSTON).score
    denver = score_location(posting("Denver, CO"), prefs, BOSTON).score
    assert boston > denver > 0
    assert denver == pytest.approx(70.0)


def test_a_named_state_matches_any_city_in_it():
    prefs = interests(places=[PlacePref(state="CO", weight=1.0)], max_distance_miles=None)
    result = score_location(posting("Colorado Springs, CO"), prefs, BOSTON)
    assert result.score > 80
    assert "a state you named" in result.evidence


def test_proximity_beats_the_state_line():
    """The whole point: 41 miles away is a short commute even in another state."""
    prefs = interests(max_distance_miles=50, relocation="no")
    near = score_location(posting("Providence, RI"), prefs, BOSTON)
    assert near.score > 80
    assert "41mi" in near.evidence or "40mi" in near.evidence
    assert "inside your 50mi radius" in near.evidence


def test_closer_scores_higher_within_the_radius():
    prefs = interests(max_distance_miles=50)
    close = score_location(posting("Cambridge, MA"), prefs, BOSTON).score
    edge = score_location(posting("Providence, RI"), prefs, BOSTON).score
    assert close > edge


def test_distance_still_orders_roles_beyond_the_radius():
    """When you'd relocate, 300 miles should still beat 2,500."""
    prefs = interests(max_distance_miles=50, relocation="willing")
    near = score_location(posting("Philadelphia, PA"), prefs, BOSTON).score
    far = score_location(posting("Los Angeles, CA"), prefs, BOSTON).score
    assert near > far


def test_evidence_names_the_actual_distance():
    prefs = interests(max_distance_miles=50, relocation="willing")
    evidence = score_location(posting("Philadelphia, PA"), prefs, BOSTON).evidence
    assert "mi from Boston, MA" in evidence


def test_home_from_interests_overrides_the_resume():
    prefs = interests(home="Denver, CO", max_distance_miles=50)
    result = score_location(posting("Boulder, CO"), prefs, BOSTON)
    assert "Denver, CO" in result.evidence


def test_unresolvable_location_falls_back_without_pretending():
    prefs = interests(relocation="willing", max_distance_miles=50)
    result = score_location(posting("Wright-Patterson AFB, Ohio"), prefs, BOSTON)
    assert "relocate" in result.evidence
    assert "mi from" not in result.evidence


def test_legacy_metros_list_still_works():
    """An interests.yaml written before weighted places must keep scoring the same."""
    prefs = interests(metros=["Boston, MA"], max_distance_miles=None)
    assert score_location(posting("Boston, MA"), prefs, BOSTON).score == 100


# --- the gate ------------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMAID_HOME", str(tmp_path))
    conn = connect(tmp_path / "t.db")
    yield conn
    conn.close()


def test_gate_filters_beyond_the_radius_when_not_relocating(db):
    prefs = interests(max_distance_miles=50, relocation="no")
    result = evaluate(db, posting("Philadelphia, PA"), BOSTON, prefs)
    assert not result.passed
    assert result.reason == "wrong_location"
    assert "beyond your 50mi radius" in result.detail


def test_gate_passes_within_the_radius(db):
    prefs = interests(max_distance_miles=50, relocation="no")
    assert evaluate(db, posting("Providence, RI"), BOSTON, prefs).passed


def test_gate_passes_a_named_place_however_far(db):
    """Naming somewhere is an explicit override of the radius."""
    prefs = interests(max_distance_miles=50, relocation="no",
                      places=[PlacePref(place="Denver, CO")])
    assert evaluate(db, posting("Denver, CO"), BOSTON, prefs).passed


def test_gate_never_filters_on_distance_when_you_would_relocate(db):
    prefs = interests(max_distance_miles=50, relocation="willing")
    assert evaluate(db, posting("Los Angeles, CA"), BOSTON, prefs).passed


def test_gate_does_not_filter_on_an_unresolvable_place_it_cannot_judge(db):
    """Only filter when sure. An unknown place with no declared places is not proof of a miss."""
    prefs = interests(max_distance_miles=50, relocation="no")
    result = evaluate(db, posting("Wright-Patterson AFB, Ohio"), BOSTON, prefs)
    assert result.passed


def test_gate_passes_remote_regardless_of_distance(db):
    prefs = interests(remote=True, max_distance_miles=50, relocation="no")
    assert evaluate(db, posting("Los Angeles, CA", remote=True), BOSTON, prefs).passed


def test_proximity_is_off_when_no_home_is_known(db):
    """With no home on the resume and none declared, distance cannot filter anything."""
    prefs = interests(max_distance_miles=50, relocation="no", places=[PlacePref(state="CA")])
    assert evaluate(db, posting("Los Angeles, CA"), Profile(), prefs).passed

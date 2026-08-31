from __future__ import annotations

from resumaid.config import Settings
from resumaid.match import gate as gate_mod
from resumaid.match.ranker import max_overcomable_gap, rank_score, recency_factor
from resumaid.match.resume_select import select
from resumaid.match.scorer import score
from resumaid.models import (
    Completeness,
    Confidence,
    DatePrecision,
    Exclusions,
    HardFilters,
    Interests,
    LocationPrefs,
    Profile,
    RawPosting,
    ResumeDoc,
    RoleFamily,
    Source,
)


def _posting(**kw):
    base = dict(
        source=Source.GREENHOUSE, source_job_id="1", company="Defense Systems",
        title="Flight Software Engineer", locations=["Boston, MA"], apply_url="u",
        description_text="Embedded flight software in C++ and Python.",
        completeness=Completeness.FULL,
    )
    base.update(kw)
    return RawPosting(**base)


def _interests(**kw):
    base = dict(
        role_families=[
            RoleFamily(name="aerospace & defense software", weight=1.0,
                       keywords=["flight software", "defense", "embedded", "autonomy"]),
            RoleFamily(name="finance", weight=0.5, keywords=["trading", "quant"], min_fit=85.0),
        ],
        locations=LocationPrefs(remote=True, metros=["Boston, MA"]),
    )
    base.update(kw)
    return Interests(**base)


PROFILE = Profile(skills=["Python", "C++", "Kubernetes"], seniority="new-grad",
                  highest_degree_level="bachelors")


# --- ranking ------------------------------------------------------------------------


def test_recency_reorders_equally_fitting_roles():
    s = Settings(secrets={})
    fresh, _, _ = rank_score(80, 2, DatePrecision.EXACT, Confidence.HIGH, s)
    stale, _, _ = rank_score(80, 60, DatePrecision.EXACT, Confidence.HIGH, s)
    assert fresh > stale


def test_recency_cannot_invert_a_large_fit_gap():
    """The bound ADR 0004 commits to: at most a ~33% gap is overcomable."""
    s = Settings(secrets={})
    strong_old, _, _ = rank_score(85, 365, DatePrecision.EXACT, Confidence.HIGH, s)
    weak_fresh, _, _ = rank_score(62, 0, DatePrecision.EXACT, Confidence.HIGH, s)
    assert strong_old > weak_fresh
    assert max_overcomable_gap(s) == 1 / s.recency_floor


def test_recency_still_differentiates_beyond_the_first_week():
    """A clipped curve saturates in days and stops separating old from very old."""
    s = Settings(secrets={})
    week = recency_factor(7, DatePrecision.EXACT, s)[0]
    month = recency_factor(30, DatePrecision.EXACT, s)[0]
    quarter = recency_factor(90, DatePrecision.EXACT, s)[0]
    assert week > month > quarter
    assert quarter >= s.recency_floor


def test_unknown_date_is_flagged_not_treated_as_fresh():
    s = Settings(secrets={})
    factor, note = recency_factor(None, DatePrecision.UNKNOWN, s)
    assert factor < 1.0
    assert "unknown" in note


def test_low_confidence_discounts_the_rank():
    s = Settings(secrets={})
    high, _, _ = rank_score(80, 5, DatePrecision.EXACT, Confidence.HIGH, s)
    low, _, _ = rank_score(80, 5, DatePrecision.EXACT, Confidence.LOW, s)
    assert low < high


# --- scoring ------------------------------------------------------------------------


def test_relevant_role_outranks_irrelevant_one():
    ints = _interests()
    good = score(_posting(), PROFILE, ints).fit_score
    bad = score(
        _posting(title="Financial Analyst", company="Bank",
                 description_text="Excel modeling and reporting."),
        PROFILE, ints,
    ).fit_score
    assert good > bad + 20


def test_every_dimension_carries_evidence():
    breakdown = score(_posting(), PROFILE, _interests())
    assert all(d.evidence for d in breakdown.dimensions)


def test_link_only_records_its_missing_description():
    breakdown = score(
        _posting(description_text=None, completeness=Completeness.LINK_ONLY),
        PROFILE, _interests(),
    )
    assert any("no description" in m for m in breakdown.missing_signals)


def test_per_family_floor_holds_a_low_priority_family_higher(db):
    """A lukewarm family stays reachable but is held to a higher bar."""
    ints = _interests()
    s = Settings(secrets={})
    assert gate_mod.floor_for("finance", ints, s.fit_floor) == 85.0
    assert gate_mod.floor_for("aerospace & defense software", ints, s.fit_floor) == s.fit_floor


# --- the gate -----------------------------------------------------------------------


def test_gate_filters_excluded_company(db):
    ints = _interests(exclusions=Exclusions(companies=["Defense Systems"]))
    result = gate_mod.evaluate(db, _posting(), PROFILE, ints)
    assert not result.passed and result.reason == "excluded_company"


def test_gate_filters_wrong_location(db):
    ints = _interests(locations=LocationPrefs(remote=False, metros=["Denver, CO"]))
    result = gate_mod.evaluate(db, _posting(locations=["Austin, TX"]), PROFILE, ints)
    assert not result.passed and result.reason == "wrong_location"


def test_gate_allows_relocation_when_declared(db):
    ints = _interests(locations=LocationPrefs(remote=False, metros=["Denver, CO"],
                                              relocation="willing"))
    assert gate_mod.evaluate(db, _posting(locations=["Austin, TX"]), PROFILE, ints).passed


def test_gate_filters_clearance_when_ineligible(db):
    ints = _interests(hard_filters=HardFilters(clearance_required_ok=False))
    posting = _posting(description_text="Requires an active TS/SCI clearance.")
    result = gate_mod.evaluate(db, posting, PROFILE, ints)
    assert not result.passed and result.reason == "clearance_required"


def test_gate_records_why_each_filter_passed(db):
    result = gate_mod.evaluate(db, _posting(), PROFILE, _interests())
    assert result.passed
    assert result.results["location"]
    assert result.results["already_applied"] == "no prior application"


# --- resume selection ----------------------------------------------------------------


def _doc(i, name, terms, master=False):
    return ResumeDoc(id=i, filename=name, path=f"/tmp/{name}", emphasis_terms=terms,
                     is_master=master)


def test_selection_picks_the_document_that_overlaps_the_posting():
    resumes = [
        _doc(1, "master.pdf", ["python", "software", "flight", "trading"], master=True),
        _doc(2, "defense.pdf", ["flight", "embedded", "autonomy"]),
        _doc(3, "finance.pdf", ["trading", "portfolio", "equities"]),
    ]
    sel = select(_posting(), resumes)
    assert sel.resume_id == 2
    assert "defense.pdf" in sel.rationale


def test_master_is_the_fallback_not_the_default():
    """A superset matches everything a little; that should not win on breadth alone."""
    resumes = [
        _doc(1, "master.pdf", ["flight", "embedded"], master=True),
        _doc(2, "defense.pdf", ["flight", "embedded"]),
    ]
    assert select(_posting(), resumes).resume_id == 2


def test_selection_falls_back_when_nothing_overlaps():
    resumes = [_doc(1, "master.pdf", ["cooking"], master=True), _doc(2, "other.pdf", ["gardening"])]
    sel = select(_posting(), resumes)
    assert sel.resume_id == 1
    assert "defaulting" in sel.rationale


def test_selection_handles_no_resumes():
    assert select(_posting(), []).resume_id is None

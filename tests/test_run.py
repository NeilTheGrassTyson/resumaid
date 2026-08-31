"""The discovery run end to end, over fixtures rather than the network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resumaid import run as run_mod
from resumaid.applications.store import record_submission
from resumaid.ingest.resume import add_resume
from resumaid.models import (
    Completeness,
    HardFilters,
    Interests,
    LocationPrefs,
    Profile,
    QueueState,
    RawPosting,
    RoleFamily,
    Source,
)
from resumaid.queue.store import approve
from resumaid.sources import adzuna, ashby, greenhouse, lever, usajobs
from resumaid.sources.registry import list_boards

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def all_postings() -> list[RawPosting]:
    return (
        greenhouse.parse(load("greenhouse_board.json"), "acmerobotics", "Acme Robotics")
        + lever.parse(load("lever_postings.json"), "scaleco", "ScaleCo")
        + ashby.parse(load("ashby_board.json"), "vectorlabs")
        + adzuna.parse(load("adzuna_search.json"))
        + usajobs.parse(load("usajobs_search.json"))
    )


@pytest.fixture
def interests() -> Interests:
    return Interests(
        role_families=[
            RoleFamily(name="aerospace & defense software", weight=1.0,
                       keywords=["flight", "embedded", "autonomy", "defense", "guidance"]),
            RoleFamily(name="general software", weight=0.8,
                       keywords=["software", "backend", "platform", "infrastructure"]),
        ],
        locations=LocationPrefs(remote=True, metros=["Boston, MA", "Denver, CO"],
                                relocation="willing"),
        hard_filters=HardFilters(degree_level_min="bachelors"),
    )


@pytest.fixture
def profile() -> Profile:
    return Profile(skills=["Python", "C++", "Rust", "Docker", "Kubernetes", "Terraform"],
                   highest_degree_level="bachelors")


def test_run_queues_relevant_and_filters_the_rest(db, profile, interests, settings, all_postings):
    report = run_mod.execute(db, profile, interests, settings, postings=all_postings)
    assert report.postings_seen == len(all_postings)
    assert report.new_entries == len(all_postings)
    assert report.queued > 0
    assert report.filtered > 0

    top = db.execute(
        "SELECT title FROM queue_entries WHERE state='queued' ORDER BY rank_score DESC"
    ).fetchone()
    assert "Flight Autonomy" in top["title"]

    # A recruiting coordinator role has no business in a software engineer's queue.
    coordinator = db.execute(
        "SELECT state FROM queue_entries WHERE title LIKE '%Recruiting%'"
    ).fetchone()
    assert coordinator["state"] == QueueState.FILTERED.value


def test_run_records_why_each_entry_was_filtered(db, profile, interests, settings, all_postings):
    run_mod.execute(db, profile, interests, settings, postings=all_postings)
    rows = db.execute(
        "SELECT filter_reason FROM queue_entries WHERE state='filtered'"
    ).fetchall()
    assert rows
    assert all(r["filter_reason"] for r in rows)


def test_run_grows_the_board_registry(db, profile, interests, settings, all_postings):
    """An aggregator hit pointing at a Greenhouse board becomes a directly-polled source."""
    report = run_mod.execute(db, profile, interests, settings, postings=all_postings)
    assert report.boards_added == 1
    assert [(b["source"], b["token"]) for b in list_boards(db)] == [("greenhouse", "heliosystems")]


def test_run_is_idempotent(db, profile, interests, settings, all_postings):
    run_mod.execute(db, profile, interests, settings, postings=all_postings)
    before = db.execute("SELECT COUNT(*) AS n FROM queue_entries").fetchone()["n"]
    second = run_mod.execute(db, profile, interests, settings, postings=all_postings)
    after = db.execute("SELECT COUNT(*) AS n FROM queue_entries").fetchone()["n"]
    assert second.new_entries == 0
    assert before == after


def test_run_never_submits(db, profile, interests, settings, all_postings):
    run_mod.execute(db, profile, interests, settings, postings=all_postings)
    assert db.execute(
        "SELECT COUNT(*) AS n FROM queue_entries WHERE state='submitted'"
    ).fetchone()["n"] == 0
    assert db.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"] == 0


def test_reposted_role_is_filtered_as_already_applied(
    db, profile, interests, settings, all_postings
):
    """The same role posted again under a new id must not come back to the queue."""
    run_mod.execute(db, profile, interests, settings, postings=all_postings)
    entry = db.execute(
        "SELECT id FROM queue_entries WHERE title LIKE '%Flight Autonomy%'"
    ).fetchone()
    approve(db, entry["id"])
    record_submission(db, entry["id"], channel="greenhouse")

    repost = RawPosting(
        source=Source.GREENHOUSE, source_job_id="9999999", company="Acme Robotics, Inc.",
        title="Software Engineer, Flight Autonomy (Remote) - Req #55512",
        locations=["Denver, CO"],  # a different office, so dedupe does not absorb it
        apply_url="https://boards.greenhouse.io/acmerobotics/jobs/9999999",
        description_text="Build and test flight software in C++ and Python.",
        completeness=Completeness.FULL,
    )
    run_mod.execute(db, profile, interests, settings, postings=[repost])
    row = db.execute(
        "SELECT state, filter_reason FROM queue_entries WHERE source_job_id='9999999'"
    ).fetchone()
    assert row["state"] == QueueState.FILTERED.value
    assert "applied" in row["filter_reason"]


def test_identical_repost_is_absorbed_by_dedupe(db, profile, interests, settings, all_postings):
    """Same role, same office, new requisition id: one entry, not two."""
    run_mod.execute(db, profile, interests, settings, postings=all_postings)
    before = db.execute("SELECT COUNT(*) AS n FROM queue_entries").fetchone()["n"]
    repost = RawPosting(
        source=Source.GREENHOUSE, source_job_id="8888888", company="Acme Robotics, Inc.",
        title="Software Engineer, Flight Autonomy (Remote) - Req #55512",
        locations=["Boston, MA"],
        apply_url="https://boards.greenhouse.io/acmerobotics/jobs/8888888",
        description_text="Build and test flight software.", completeness=Completeness.FULL,
    )
    run_mod.execute(db, profile, interests, settings, postings=[repost])
    assert db.execute("SELECT COUNT(*) AS n FROM queue_entries").fetchone()["n"] == before


def test_run_writes_a_run_row(db, profile, interests, settings, all_postings):
    run_mod.execute(db, profile, interests, settings, postings=all_postings)
    row = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert row["finished_at"]
    assert row["postings_seen"] == len(all_postings)


def test_paste_upgrade_rescore_lifts_confidence(db, profile, interests, settings, all_postings):
    from resumaid.queue.store import paste_description

    run_mod.execute(db, profile, interests, settings, postings=all_postings)
    entry = db.execute(
        "SELECT id, fit_score FROM queue_entries WHERE completeness='partial' LIMIT 1"
    ).fetchone()
    paste_description(
        db, entry["id"],
        "Deep Kubernetes, Terraform and Docker experience. You will own our Go services.",
    )
    run_mod.execute(db, profile, interests, settings, postings=[])
    after = db.execute(
        "SELECT completeness, score_confidence FROM queue_entries WHERE id=?", (entry["id"],)
    ).fetchone()
    assert after["completeness"] == "full"
    assert after["score_confidence"] == "high"


def test_resume_selection_is_recorded_on_queued_entries(
    db, profile, interests, settings, all_postings, tmp_path
):
    resume = tmp_path / "defense.md"
    resume.write_text("Flight software, embedded C++, autonomy, guidance systems.")
    add_resume(db, resume)
    run_mod.execute(db, profile, interests, settings, postings=all_postings)
    row = db.execute(
        "SELECT recommended_resume_id, selection_rationale FROM queue_entries"
        " WHERE state='queued' LIMIT 1"
    ).fetchone()
    assert row["recommended_resume_id"]
    assert row["selection_rationale"]

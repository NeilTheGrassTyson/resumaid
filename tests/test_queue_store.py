from __future__ import annotations

import pytest

from resumaid.applications.store import find_duplicate, record_submission, update_application
from resumaid.models import Completeness, QueueState, RejectionReason, Source
from resumaid.queue import state as st
from resumaid.queue.store import (
    _cap_per_company,
    approve,
    paste_description,
    reject,
    slate,
    snooze,
    upsert_posting,
    wake_snoozed,
)


def test_upsert_is_idempotent(db, posting):
    a = upsert_posting(db, posting())
    b = upsert_posting(db, posting())
    assert a.entry_id == b.entry_id
    assert not b.created
    assert db.execute("SELECT COUNT(*) AS n FROM queue_entries").fetchone()["n"] == 1


def test_dedupe_collapses_same_role_across_sources(db, posting):
    upsert_posting(db, posting(source=Source.ADZUNA, source_job_id="a1",
                               company="Acme Robotics, Inc.", title="Software Engineer (Remote)",
                               description_text=None, completeness=Completeness.LINK_ONLY))
    upsert_posting(db, posting(source=Source.GREENHOUSE, source_job_id="g1"))
    assert db.execute("SELECT COUNT(*) AS n FROM queue_entries").fetchone()["n"] == 1


def test_better_source_upgrades_the_record(db, posting):
    """An aggregator hit later found on the ATS gains its full description."""
    first = upsert_posting(db, posting(source=Source.ADZUNA, source_job_id="a1",
                                       description_text=None,
                                       completeness=Completeness.LINK_ONLY))
    second = upsert_posting(db, posting(source=Source.GREENHOUSE, source_job_id="g1"))
    assert second.entry_id == first.entry_id
    assert second.updated_from_better_source
    row = db.execute("SELECT * FROM queue_entries WHERE id=?", (first.entry_id,)).fetchone()
    assert row["source"] == "greenhouse"
    assert row["completeness"] == "full"
    assert row["description_text"]
    assert "adzuna" in row["also_seen_in"]


def test_worse_source_does_not_downgrade(db, posting):
    first = upsert_posting(db, posting(source=Source.GREENHOUSE, source_job_id="g1"))
    upsert_posting(db, posting(source=Source.ADZUNA, source_job_id="a1",
                               description_text=None, completeness=Completeness.LINK_ONLY))
    row = db.execute("SELECT * FROM queue_entries WHERE id=?", (first.entry_id,)).fetchone()
    assert row["source"] == "greenhouse"
    assert row["description_text"]


def test_paste_upgrades_link_only(db, posting):
    entry = upsert_posting(db, posting(description_text=None,
                                       completeness=Completeness.LINK_ONLY))
    paste_description(db, entry.entry_id, "  Pasted description text.  ")
    row = db.execute("SELECT * FROM queue_entries WHERE id=?", (entry.entry_id,)).fetchone()
    assert row["completeness"] == "full"
    assert row["score_confidence"] == "high"
    assert row["description_source"] == "human_paste"
    assert row["scored_at"] is None  # marked for re-scoring


def test_paste_rejects_empty(db, posting):
    entry = upsert_posting(db, posting())
    with pytest.raises(ValueError):
        paste_description(db, entry.entry_id, "   ")


def test_snooze_then_wake(db, posting):
    entry = upsert_posting(db, posting())
    st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    snooze(db, entry.entry_id, days=-1)  # already elapsed
    assert wake_snoozed(db) == 1
    row = db.execute("SELECT state, snooze_until FROM queue_entries WHERE id=?",
                     (entry.entry_id,)).fetchone()
    assert row["state"] == "queued"
    assert row["snooze_until"] is None


def test_reject_records_reason(db, posting):
    entry = upsert_posting(db, posting())
    st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    reject(db, entry.entry_id, RejectionReason.WRONG_LOCATION, note="too far")
    row = db.execute("SELECT * FROM queue_entries WHERE id=?", (entry.entry_id,)).fetchone()
    assert row["state"] == "rejected"
    assert row["rejection_reason"] == "wrong_location"
    assert row["decision_note"] == "too far"


class _Row(dict):
    def __getitem__(self, k):
        return dict.__getitem__(self, k)


def test_diversity_cap_interleaves_companies():
    rows = [_Row(company=c, id=i) for i, c in enumerate(
        ["Acme", "Acme", "Acme", "Beta", "Beta", "Gamma"])]
    out = _cap_per_company(rows, cap=2)
    top4 = [r["company"] for r in out[:4]]
    assert top4 == ["Acme", "Beta", "Gamma", "Acme"]
    assert len(out) == len(rows)  # overflow trails, nothing lost


def test_slate_is_a_ceiling_not_a_quota(db, posting, settings):
    """Three roles clearing the bar means three shown, never a padded five."""
    for i in range(3):
        entry = upsert_posting(db, posting(source_job_id=str(i), title=f"Engineer {i}"))
        db.execute("UPDATE queue_entries SET rank_score=? WHERE id=?", (90 - i, entry.entry_id))
        st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    assert len(slate(db, settings)) == 3


def test_duplicate_guard_survives_name_variants(db, posting):
    entry = upsert_posting(db, posting())
    st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    approve(db, entry.entry_id)
    record_submission(db, entry.entry_id, channel="greenhouse")
    assert find_duplicate(db, "ACME ROBOTICS, LLC", "Software Engineer (Remote)") is not None
    assert find_duplicate(db, "Different Co", "Software Engineer") is None


def test_update_application_rejects_unknown_field(db, posting):
    entry = upsert_posting(db, posting())
    st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    approve(db, entry.entry_id)
    app_id = record_submission(db, entry.entry_id)
    with pytest.raises(ValueError):
        update_application(db, app_id, company="Hacked")


def test_recording_oa_sets_timestamp(db, posting):
    entry = upsert_posting(db, posting())
    st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    approve(db, entry.entry_id)
    app_id = record_submission(db, entry.entry_id)
    update_application(db, app_id, oa_received=1, oa_platform="Karat")
    row = db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    assert row["oa_received_at"]

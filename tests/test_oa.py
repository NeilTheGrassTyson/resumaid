from __future__ import annotations

from resumaid.applications.oa import assess, scan_posting_text
from resumaid.applications.store import record_submission, update_application
from resumaid.models import OAExpectation, QueueState
from resumaid.queue import state as st
from resumaid.queue.store import approve, upsert_posting


def test_phrase_hit_carries_a_quote():
    score, evidence = scan_posting_text("You will complete a timed challenge before onsite.")
    assert score > 0
    assert evidence[0].quote


def test_negation_is_not_cancelled_by_its_own_phrase():
    """'No coding tests' contains 'coding test'; naive scanning would net to zero."""
    score, _ = scan_posting_text("We have no coding tests in our process.")
    assert score < 0


def test_link_only_reports_unknown_not_a_guess(db):
    a = assess(db, company="Acme", description_text=None)
    assert a.expected is OAExpectation.UNKNOWN
    assert any("no description" in e.detail for e in a.evidence)


def test_history_outweighs_posting_text(db, posting):
    """Once the user records a real OA, that beats anything the text says."""
    entry = upsert_posting(db, posting())
    st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    approve(db, entry.entry_id)
    app_id = record_submission(db, entry.entry_id)
    update_application(db, app_id, oa_received=1, oa_platform="HackerRank")

    a = assess(db, company="Acme Robotics", description_text="A friendly chat, nothing formal.")
    assert a.expected is OAExpectation.LIKELY
    assert any(e.kind == "history" for e in a.evidence)


def test_posting_text_drives_prediction_without_history(db):
    a = assess(db, company="Nobody", description_text="Please complete our HackerRank assessment.")
    assert a.expected is OAExpectation.LIKELY
    assert any(e.kind == "posting_text" for e in a.evidence)

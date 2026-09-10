"""The tests that make CLAUDE.md constraint 1 a property of the code.

If any of these fail, the change that broke them is wrong. They are not adjustable to fit new
behavior; the behavior is adjustable to fit them.
"""

from __future__ import annotations

import pytest

from resumaid.applications.store import record_submission
from resumaid.models import QueueState
from resumaid.queue import state as st
from resumaid.queue.state import TRANSITIONS, IllegalTransition, UnauthorizedActor
from resumaid.queue.store import approve, upsert_posting


def _queued(db, posting, **kw):
    entry = upsert_posting(db, posting(**kw))
    st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    return entry.entry_id


def test_pipeline_cannot_submit(db, posting):
    entry_id = _queued(db, posting)
    approve(db, entry_id)
    with pytest.raises(UnauthorizedActor):
        st.transition(db, entry_id, QueueState.SUBMITTED, actor=st.PIPELINE)


def test_system_cannot_submit(db, posting):
    entry_id = _queued(db, posting)
    approve(db, entry_id)
    with pytest.raises(UnauthorizedActor):
        st.transition(db, entry_id, QueueState.SUBMITTED, actor=st.SYSTEM)


def test_pipeline_cannot_approve(db, posting):
    """Approval is a human judgment even though it sends nothing."""
    entry_id = _queued(db, posting)
    with pytest.raises(UnauthorizedActor):
        st.transition(db, entry_id, QueueState.APPROVED, actor=st.PIPELINE)


def test_no_state_reaches_submitted_except_approved():
    """There is exactly one door into `submitted`, and it opens from `approved`."""
    doors = [frm for frm, tos in TRANSITIONS.items() if QueueState.SUBMITTED in tos]
    assert doors == [QueueState.APPROVED]


def test_cannot_skip_review(db, posting):
    entry_id = _queued(db, posting)
    with pytest.raises(IllegalTransition):
        st.transition(db, entry_id, QueueState.SUBMITTED, actor=st.HUMAN)


def test_submitted_is_terminal():
    assert TRANSITIONS[QueueState.SUBMITTED] == set()


def test_database_trigger_blocks_unlogged_submit(db, posting):
    """Even bypassing the service layer entirely, the database refuses."""
    entry_id = _queued(db, posting)
    approve(db, entry_id)
    with pytest.raises(Exception, match="constraint 1"):
        db.execute("UPDATE queue_entries SET state='submitted' WHERE id=?", (entry_id,))


def test_database_trigger_rejects_non_human_log_row(db, posting):
    """A forged state_log row with a non-human actor does not satisfy the trigger."""
    entry_id = _queued(db, posting)
    approve(db, entry_id)
    db.execute(
        "INSERT INTO state_log (queue_entry_id, to_state, actor, at)"
        " VALUES (?, 'submitted', 'pipeline', '2026-01-01')",
        (entry_id,),
    )
    with pytest.raises(Exception, match="constraint 1"):
        db.execute("UPDATE queue_entries SET state='submitted' WHERE id=?", (entry_id,))


def test_human_submission_succeeds_and_logs(db, posting):
    entry_id = _queued(db, posting)
    approve(db, entry_id)
    app_id = record_submission(db, entry_id, channel="greenhouse")
    assert app_id > 0
    row = db.execute(
        "SELECT state, submitted_at FROM queue_entries WHERE id=?", (entry_id,)
    ).fetchone()
    assert row["state"] == "submitted"
    assert row["submitted_at"]
    log = db.execute(
        "SELECT actor FROM state_log WHERE queue_entry_id=? AND to_state='submitted'", (entry_id,)
    ).fetchone()
    assert log["actor"] == "human"


def test_full_pipeline_run_submits_nothing(db, posting, settings):
    """The whole discover -> score -> queue path writes zero submissions."""
    from resumaid.match.pipeline import score_and_gate
    from resumaid.models import Interests, Profile

    for i in range(5):
        upsert_posting(db, posting(source_job_id=str(i), title=f"Engineer {i}"))
    score_and_gate(db, Profile(skills=["python"]), Interests(), settings, resumes=[])

    submitted = db.execute(
        "SELECT COUNT(*) AS n FROM queue_entries"
        " WHERE state='submitted' OR submitted_at IS NOT NULL"
    ).fetchone()["n"]
    assert submitted == 0
    logged = db.execute(
        "SELECT COUNT(*) AS n FROM state_log WHERE to_state='submitted'"
    ).fetchone()["n"]
    assert logged == 0
    assert db.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"] == 0

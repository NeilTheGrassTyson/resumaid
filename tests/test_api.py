"""API routes, including the ones that must refuse to exist."""

from __future__ import annotations

from resumaid.applications.store import record_submission
from resumaid.models import QueueState
from resumaid.queue import state as st
from resumaid.queue.store import approve, upsert_posting


def _queued(db, posting, **kw):
    entry = upsert_posting(db, posting(**kw))
    st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    db.execute("UPDATE queue_entries SET fit_score=80, rank_score=80 WHERE id=?",
               (entry.entry_id,))
    return entry.entry_id


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_slate_returns_ranked_entries(client, db, posting):
    _queued(db, posting, source_job_id="1", title="Software Engineer")
    body = client.get("/api/queue").json()
    assert body["total_queued"] == 1
    assert body["entries"][0]["title"] == "Software Engineer"


def test_entry_carries_its_explanation(client, db, posting, settings):
    """The 'why is this here' pane has to be answerable from the API alone."""
    from resumaid.ingest.interests import load_interests, load_profile
    from resumaid.match.pipeline import score_and_gate

    _queued(db, posting, source_job_id="1")
    score_and_gate(db, load_profile(), load_interests(), settings, [])
    entry = client.get("/api/queue").json()["entries"][0]
    assert entry["dimensions"]
    assert all(d["evidence"] for d in entry["dimensions"])
    assert entry["oa_expected"]


def test_approve_then_submitted(client, db, posting):
    entry_id = _queued(db, posting)
    assert client.post(f"/api/queue/{entry_id}/approve", json={}).json()["state"] == "approved"
    assert [e["id"] for e in client.get("/api/queue/ready").json()] == [entry_id]
    body = client.post(f"/api/queue/{entry_id}/submitted", json={"channel": "greenhouse"}).json()
    assert body["state"] == "submitted"
    assert client.get("/api/applications").json()[0]["company"] == "Acme Robotics"


def test_cannot_submit_without_approving(client, db, posting):
    """Skipping the human review step is not a route the API offers."""
    entry_id = _queued(db, posting)
    assert client.post(f"/api/queue/{entry_id}/submitted", json={}).status_code == 409


def test_no_route_applies_on_the_users_behalf(client):
    """Constraint 1, asserted against the published surface.

    Every mutating queue route either records a human decision or prepares materials. If a
    route ever appears whose name implies the tool contacts an employer, this fails.
    """
    schema = client.get("/openapi.json").json()
    forbidden = ("apply", "autosubmit", "auto-submit", "autofill", "auto-fill", "send")
    offenders = [
        path for path in schema["paths"]
        if any(word in path.lower() for word in forbidden)
    ]
    assert offenders == []


def test_reject_records_the_reason(client, db, posting):
    entry_id = _queued(db, posting)
    body = client.post(f"/api/queue/{entry_id}/reject",
                       json={"reason": "wrong_location", "note": "too far"}).json()
    assert body["state"] == "rejected"


def test_reject_rejects_an_unknown_reason(client, db, posting):
    entry_id = _queued(db, posting)
    assert client.post(f"/api/queue/{entry_id}/reject",
                       json={"reason": "because"}).status_code == 422


def test_paste_upgrades_and_rescore(client, db, posting):
    from resumaid.models import Completeness

    entry_id = _queued(db, posting, description_text=None,
                       completeness=Completeness.LINK_ONLY)
    db.execute("UPDATE queue_entries SET completeness='link_only', score_confidence='low',"
               " description_text=NULL WHERE id=?", (entry_id,))
    body = client.post(f"/api/queue/{entry_id}/paste",
                       json={"text": "Build flight software in Python and C++."}).json()
    assert body["completeness"] == "full"
    assert body["score_confidence"] == "high"
    assert body["description_source"] == "human_paste"


def test_paste_rejects_empty_text(client, db, posting):
    entry_id = _queued(db, posting)
    assert client.post(f"/api/queue/{entry_id}/paste", json={"text": "  "}).status_code == 400


def test_unapprove_returns_to_queue(client, db, posting):
    entry_id = _queued(db, posting)
    client.post(f"/api/queue/{entry_id}/approve", json={})
    assert client.post(f"/api/queue/{entry_id}/unapprove").json()["state"] == "queued"


def test_missing_entry_is_404(client):
    assert client.get("/api/queue/999").status_code == 404
    assert client.post("/api/queue/999/approve", json={}).status_code == 404


def test_application_update_records_oa(client, db, posting):
    entry_id = _queued(db, posting)
    approve(db, entry_id)
    app_id = record_submission(db, entry_id)
    body = client.patch(f"/api/applications/{app_id}",
                        json={"outcome": "oa", "oa_received": True,
                              "oa_platform": "Karat"}).json()
    assert body["oa_received"] is True
    assert body["oa_platform"] == "Karat"
    assert body["oa_received_at"]


def test_export_is_excel_safe(client, db, posting):
    entry_id = _queued(db, posting, company="Café Ordinateur")
    approve(db, entry_id)
    record_submission(db, entry_id)
    response = client.get("/api/applications/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM, so Excel reads UTF-8
    assert "Café Ordinateur" in response.content.decode("utf-8-sig")


def test_filtered_entries_stay_auditable(client, db, posting):
    entry = upsert_posting(db, posting())
    st.transition(db, entry.entry_id, QueueState.FILTERED, actor=st.PIPELINE,
                  note="below_fit_floor", extra={"filter_reason": "fit 40 below floor 60"})
    body = client.get("/api/queue/filtered").json()
    assert body[0]["filter_reason"] == "fit 40 below floor 60"

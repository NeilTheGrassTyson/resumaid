"""Setup routes: resume upload, profile, interests, boards.

The upload path gets the most attention here because it is the only route that accepts a file
from outside and writes it into the user's data directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from resumaid.ingest.interests import load_interests, load_profile
from resumaid.ingest.resume import list_resumes
from resumaid.models import Source
from resumaid.sources.registry import list_boards, register

FIXTURES = Path(__file__).parent / "fixtures"
PDF = FIXTURES / "sample_resume.pdf"

RESUME_MD = b"""Jane Q Public
Boston, MA | jane@example.com

Education
B.S. Computer Science, State University, May 2026

Skills
Languages: Python, C++, Rust
"""


def upload(client, name="resume.md", content=RESUME_MD, **params):
    return client.post(
        "/api/resumes",
        files={"file": (name, content, "application/octet-stream")},
        params=params,
    )


# --- resume upload ---------------------------------------------------------------------


def test_upload_registers_a_resume(client, db, tmp_path):
    response = upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "resume.md"
    assert len(list_resumes(db)) == 1
    # The kept copy lives in the data directory, not wherever it was staged.
    assert Path(body["path"]).parent == tmp_path / "resumes"
    assert Path(body["path"]).exists()


def test_upload_parses_a_profile(client, tmp_path):
    upload(client)
    profile = load_profile(tmp_path / "profile.yaml")
    assert profile.highest_degree_level == "bachelors"
    assert profile.locations == ["Boston, MA"]
    assert any("Python" in s for s in profile.skills)


def test_upload_accepts_a_real_pdf(client, db):
    """PDFs are how resumes actually arrive."""
    response = upload(client, name="resume.pdf", content=PDF.read_bytes())
    assert response.status_code == 201
    assert list_resumes(db)[0].emphasis_terms


def test_upload_can_mark_a_master(client, db):
    upload(client, name="master.md", is_master=True)
    assert list_resumes(db)[0].is_master is True


@pytest.mark.parametrize("name", ["resume.rtf", "resume.pages", "resume", "resume.exe"])
def test_unsupported_formats_are_rejected(client, db, tmp_path, name):
    response = upload(client, name=name)
    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"]
    assert list_resumes(db) == []
    # Nothing was written into the resumes directory.
    assert list((tmp_path / "resumes").glob("*")) == []


def test_an_oversized_upload_is_rejected(client, db, tmp_path):
    response = upload(client, content=b"x" * (6 * 1024 * 1024))
    assert response.status_code == 413
    assert list_resumes(db) == []
    assert list((tmp_path / "resumes").glob("*")) == []


def test_an_empty_upload_is_rejected(client, db):
    assert upload(client, content=b"").status_code == 400
    assert list_resumes(db) == []


def test_a_file_with_no_extractable_text_leaves_nothing_behind(client, db, tmp_path):
    """A scanned image or a corrupt file must not land in the resumes directory."""
    response = upload(client, content=b"   \n\n   ")
    assert response.status_code == 400
    assert list_resumes(db) == []
    assert list((tmp_path / "resumes").glob("*")) == []


def test_a_path_in_the_filename_cannot_escape_the_resumes_directory(client, tmp_path):
    """A traversal attempt is reduced to its basename before anything is written."""
    response = upload(client, name="../../evil.md")
    assert response.status_code == 201
    written = Path(response.json()["path"])
    assert written.parent == tmp_path / "resumes"
    assert written.name == "evil.md"


def test_delete_forgets_the_record_but_keeps_the_file(client, db, tmp_path):
    resume_id = upload(client).json()["id"]
    kept = Path(list_resumes(db)[0].path)
    assert client.delete(f"/api/resumes/{resume_id}").status_code == 204
    assert list_resumes(db) == []
    assert kept.exists(), "the user's own file must not be deleted"


def test_delete_of_a_missing_resume_is_404(client):
    assert client.delete("/api/resumes/999").status_code == 404


def test_setting_a_master_clears_the_previous_one(client, db):
    first = upload(client, name="a.md", is_master=True).json()["id"]
    second = upload(client, name="b.md").json()["id"]
    assert client.post(f"/api/resumes/{second}/master").status_code == 200
    masters = {d.id: d.is_master for d in list_resumes(db)}
    assert masters[second] is True
    assert masters[first] is False


# --- profile ----------------------------------------------------------------------------


def test_profile_can_be_corrected(client, tmp_path):
    upload(client)
    edited = load_profile(tmp_path / "profile.yaml").model_dump(mode="json")
    edited["skills"] = ["Fortran"]
    edited["highest_degree_level"] = "masters"
    assert client.put("/api/profile", json=edited).status_code == 200
    assert load_profile(tmp_path / "profile.yaml").skills == ["Fortran"]


def test_reparse_discards_hand_edits(client, tmp_path):
    upload(client)
    edited = load_profile(tmp_path / "profile.yaml").model_dump(mode="json")
    edited["skills"] = ["Fortran"]
    client.put("/api/profile", json=edited)
    body = client.post("/api/profile/reparse").json()
    assert "Fortran" not in body["skills"]
    assert any("Python" in s for s in body["skills"])


def test_reparse_without_resumes_is_rejected(client):
    assert client.post("/api/profile/reparse").status_code == 400


# --- interests --------------------------------------------------------------------------


VALID_INTERESTS = {
    "role_families": [
        {"name": "aerospace", "weight": 1.0, "keywords": ["flight", "autonomy"], "min_fit": None}
    ],
    "industries": [],
    "locations": {
        "remote": True, "home": "Boston, MA", "max_distance_miles": 50,
        "places": [{"place": "Denver, CO", "state": None, "weight": 0.7}],
        "metros": [], "relocation": "no",
    },
    "hard_filters": {
        "degree_level_min": "bachelors", "seniority": [], "citizenship_required_ok": True,
        "clearance_required_ok": False, "employment_types": [],
    },
    "exclusions": {"companies": [], "title_keywords": []},
    "throughput": {"submissions_per_day": 5},
}


def test_interests_round_trip(client, tmp_path):
    assert client.put("/api/interests", json=VALID_INTERESTS).status_code == 200
    saved = load_interests(tmp_path / "interests.yaml")
    assert saved.role_families[0].name == "aerospace"
    assert saved.locations.home == "Boston, MA"
    assert saved.locations.places[0].weight == 0.7


def test_invalid_interests_leave_the_file_untouched(client, tmp_path):
    """A rejected payload must not half-write interests.yaml."""
    client.put("/api/interests", json=VALID_INTERESTS)
    before = (tmp_path / "interests.yaml").read_text()

    broken = {**VALID_INTERESTS, "locations": {**VALID_INTERESTS["locations"],
                                               "places": [{"place": "X", "state": "CO"}]}}
    response = client.put("/api/interests", json=broken)
    assert response.status_code == 422  # exactly one of place/state
    assert (tmp_path / "interests.yaml").read_text() == before


def test_interests_yaml_stays_hand_editable(client, tmp_path):
    """What the API writes must be what `interests edit` can read back."""
    client.put("/api/interests", json=VALID_INTERESTS)
    raw = yaml.safe_load((tmp_path / "interests.yaml").read_text())
    assert raw["throughput"]["submissions_per_day"] == 5
    assert raw["locations"]["relocation"] == "no"


# --- boards -----------------------------------------------------------------------------


def test_add_board_by_url(client, db):
    response = client.post("/api/boards", json={"url": "https://boards.greenhouse.io/anduril"})
    assert response.status_code == 201
    assert response.json() == {"source": "greenhouse", "token": "anduril", "added": True}
    assert [(b["source"], b["token"]) for b in list_boards(db)] == [("greenhouse", "anduril")]


def test_adding_the_same_board_twice_reports_it(client):
    client.post("/api/boards", json={"url": "https://jobs.lever.co/scaleco"})
    assert client.post("/api/boards", json={"url": "https://jobs.lever.co/scaleco"}).json()[
        "added"
    ] is False


def test_a_non_ats_url_is_rejected_with_a_useful_message(client):
    response = client.post("/api/boards", json={"url": "https://careers.example.com/jobs"})
    assert response.status_code == 400
    assert "greenhouse" in response.json()["detail"]


def test_a_workday_url_is_rejected(client):
    """Workday stays out until the founder decides — including from the browser."""
    response = client.post(
        "/api/boards", json={"url": "https://acme.wd1.myworkdayjobs.com/careers"}
    )
    assert response.status_code == 400


def test_board_can_be_added_by_source_and_token(client, db):
    response = client.post("/api/boards", json={"source": "ashby", "token": "vectorlabs"})
    assert response.status_code == 201
    assert list_boards(db)[0]["token"] == "vectorlabs"


def test_remove_disables_rather_than_deletes(client, db):
    """Deleting would let a self-registering board silently come back next run."""
    register(db, Source.GREENHOUSE, "acme")
    board_id = list_boards(db)[0]["id"]
    assert client.delete(f"/api/boards/{board_id}").status_code == 204
    assert list_boards(db, enabled_only=True) == []
    assert len(list_boards(db, enabled_only=False)) == 1


def test_a_disabled_board_can_be_re_enabled(client, db):
    register(db, Source.GREENHOUSE, "acme")
    board_id = list_boards(db)[0]["id"]
    client.delete(f"/api/boards/{board_id}")
    assert client.post(f"/api/boards/{board_id}/enable").status_code == 204
    assert len(list_boards(db, enabled_only=True)) == 1


def test_removing_a_missing_board_is_404(client):
    assert client.delete("/api/boards/999").status_code == 404


# --- setup status -------------------------------------------------------------------------


def test_setup_status_reports_what_is_missing(client):
    assert client.get("/api/setup/status").json()["ready"] is False


def test_setup_status_is_ready_once_configured(client):
    upload(client)
    client.put("/api/interests", json=VALID_INTERESTS)
    client.post("/api/boards", json={"url": "https://boards.greenhouse.io/anduril"})
    status = client.get("/api/setup/status").json()
    assert status == {"resumes": 1, "role_families": 1, "boards": 1, "ready": True}


# --- the constraint that governs all of this ------------------------------------------------


def test_no_setup_route_can_submit_an_application(client, db):
    """Widening the API surface must not widen what the tool can do on its own."""
    upload(client)
    client.put("/api/interests", json=VALID_INTERESTS)
    client.post("/api/boards", json={"url": "https://boards.greenhouse.io/anduril"})
    assert db.execute(
        "SELECT COUNT(*) AS n FROM queue_entries WHERE state='submitted'"
    ).fetchone()["n"] == 0
    assert db.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"] == 0

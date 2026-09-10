from __future__ import annotations

import pytest

from resumaid.config import Settings
from resumaid.db import connect
from resumaid.models import Completeness, RawPosting, Source


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMAID_HOME", str(tmp_path))
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


@pytest.fixture
def settings():
    return Settings(secrets={})


@pytest.fixture
def posting():
    def make(**kw):
        base = dict(
            source=Source.GREENHOUSE,
            source_job_id="1",
            company="Acme Robotics",
            title="Software Engineer",
            locations=["Boston, MA"],
            apply_url="https://boards.greenhouse.io/acme/jobs/1",
            description_text="Build things. Python and C++.",
            completeness=Completeness.FULL,
        )
        base.update(kw)
        return RawPosting(**base)

    return make


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    """A TestClient wired to the per-test database and data directory."""
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from fastapi.testclient import TestClient

    from resumaid.api import deps
    from resumaid.api.app import app
    from resumaid.ingest.interests import save_interests, save_profile
    from resumaid.models import HardFilters, Interests, LocationPrefs, Profile, RoleFamily

    save_profile(
        Profile(skills=["Python", "C++", "Kubernetes"], highest_degree_level="bachelors"),
        tmp_path / "profile.yaml",
    )
    save_interests(
        Interests(
            role_families=[
                RoleFamily(name="software", weight=1.0,
                           keywords=["software", "engineer", "flight", "platform"])
            ],
            locations=LocationPrefs(remote=True, metros=["Boston, MA"], relocation="willing"),
            hard_filters=HardFilters(),
        ),
        tmp_path / "interests.yaml",
    )

    app.dependency_overrides[deps.get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()

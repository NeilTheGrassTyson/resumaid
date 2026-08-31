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

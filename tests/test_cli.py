"""The CLI surface, and the rule that it mirrors the API.

ADR 0002 promises every mutating API route has a CLI twin calling the same service function, so
the loop stays scriptable and the UI is never the only way to reach a state transition. That
promise is worth enforcing rather than remembering — see `test_every_mutating_route_has_a_cli_twin`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from resumaid import run as run_mod
from resumaid.api.app import app as fastapi_app
from resumaid.cli import app as cli_app
from resumaid.config import Settings
from resumaid.db import connect
from resumaid.ingest.interests import load_interests, load_profile
from resumaid.sources import adzuna, ashby, greenhouse, lever, usajobs

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()

RESUME_TEXT = """\
Jane Q Public

Education
B.S. Computer Science, State University, May 2026

Skills
Languages: Python, C++, Rust
Tools: Docker, Kubernetes

Experience
Software Engineer Intern | Acme Robotics   Jun 2025 - Aug 2025
- Built a flight-control test harness in C++
"""

INTERESTS = {
    "role_families": [
        {
            "name": "aerospace & defense software",
            "weight": 1.0,
            "keywords": ["flight", "embedded", "autonomy", "defense", "guidance"],
        },
        {
            "name": "general software",
            "weight": 0.8,
            "keywords": ["software", "backend", "platform", "infrastructure"],
        },
    ],
    "industries": [],
    "locations": {"remote": True, "metros": ["Boston, MA", "Denver, CO"], "relocation": "willing"},
    "hard_filters": {
        "degree_level_min": "bachelors",
        "seniority": [],
        "citizenship_required_ok": True,
        "clearance_required_ok": False,
        "employment_types": [],
    },
    "exclusions": {"companies": [], "title_keywords": []},
    "throughput": {"submissions_per_day": 5},
}


def invoke(*args: str):
    result = runner.invoke(cli_app, list(args))
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A configured data directory.

    The CLI reads RESUMAID_HOME, so setting it is all the wiring these tests need.
    """
    monkeypatch.setenv("RESUMAID_HOME", str(tmp_path))
    assert invoke("init").exit_code == 0
    (tmp_path / "interests.yaml").write_text(yaml.safe_dump(INTERESTS), encoding="utf-8")
    resume = tmp_path / "resume.md"
    resume.write_text(RESUME_TEXT, encoding="utf-8")
    assert invoke("resume", "add", str(resume), "--master").exit_code == 0
    return tmp_path


@pytest.fixture
def seeded(home):
    """The same fixture postings the run tests use, pushed through the real pipeline."""

    def load(name):
        return json.loads((FIXTURES / name).read_text())

    postings = (
        greenhouse.parse(load("greenhouse_board.json"), "acmerobotics", "Acme Robotics")
        + lever.parse(load("lever_postings.json"), "scaleco", "ScaleCo")
        + ashby.parse(load("ashby_board.json"), "vectorlabs")
        + adzuna.parse(load("adzuna_search.json"))
        + usajobs.parse(load("usajobs_search.json"))
    )
    conn = connect()
    run_mod.execute(conn, load_profile(), load_interests(), Settings(secrets={}), postings=postings)
    conn.close()
    return home


def queued_id(home: Path) -> int:
    conn = connect()
    row = conn.execute(
        "SELECT id FROM queue_entries WHERE state='queued' ORDER BY rank_score DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None, "expected the fixture run to queue something"
    return row["id"]


# --- the ADR 0002 twin rule ------------------------------------------------------------

#: Every mutating API route, and the CLI command that calls the same service function.
#: Adding a route means adding its twin here and in the CLI, or the rule has quietly lapsed.
API_TO_CLI = {
    "/api/run": "run",
    "/api/applications/{app_id}": "app update",
    "/api/queue/{entry_id}/approve": "queue approve",
    "/api/queue/{entry_id}/reject": "queue reject",
    "/api/queue/{entry_id}/snooze": "queue snooze",
    "/api/queue/{entry_id}/paste": "queue paste",
    "/api/queue/{entry_id}/unapprove": "queue unapprove",
    "/api/queue/{entry_id}/submitted": "submitted",
}

MUTATING_VERBS = {"post", "patch", "put", "delete"}


def cli_command_names() -> set[str]:
    """Every command the CLI exposes, as the user would type it."""
    names: set[str] = set()

    def walk(typer_app, prefix: str = "") -> None:
        for command in typer_app.registered_commands:
            name = command.name or command.callback.__name__.replace("_", "-")
            names.add(f"{prefix}{name}")
        for group in typer_app.registered_groups:
            walk(group.typer_instance, prefix=f"{prefix}{group.name} ")

    walk(cli_app)
    return names


def mutating_api_paths() -> set[str]:
    schema = fastapi_app.openapi()
    return {
        path
        for path, operations in schema["paths"].items()
        if MUTATING_VERBS & set(operations) and path.startswith("/api")
    }


def test_every_mutating_route_has_a_cli_twin():
    """ADR 0002's promise, enforced.

    If this fails, either a route was added without its CLI twin, or the mapping above is stale.
    Both are worth stopping for: without the twin, the UI becomes the only way to reach a state
    transition, and the pipeline stops being scriptable and testable without a browser.
    """
    untwinned = mutating_api_paths() - set(API_TO_CLI)
    assert not untwinned, f"mutating API routes with no CLI twin recorded: {sorted(untwinned)}"

    commands = cli_command_names()
    missing = {path: cmd for path, cmd in API_TO_CLI.items() if cmd not in commands}
    assert not missing, f"CLI commands named in the mapping but absent: {missing}"


def test_the_mapping_has_no_stale_entries():
    stale = set(API_TO_CLI) - mutating_api_paths()
    assert not stale, f"mapping names routes that no longer exist: {sorted(stale)}"


# --- setup -----------------------------------------------------------------------------


def test_init_creates_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMAID_HOME", str(tmp_path))
    result = invoke("init")
    assert result.exit_code == 0
    assert (tmp_path / "interests.yaml").exists()
    assert (tmp_path / "resumaid.db").exists()


def test_init_writes_a_profile_agnostic_template(tmp_path, monkeypatch):
    """No role family, employer, or industry is a default — CLAUDE.md's core generality rule."""
    monkeypatch.setenv("RESUMAID_HOME", str(tmp_path))
    invoke("init")
    interests = yaml.safe_load((tmp_path / "interests.yaml").read_text())
    assert interests["role_families"] == []
    assert interests["industries"] == []
    assert interests["exclusions"]["companies"] == []


def test_resume_add_parses_a_profile(home):
    assert (home / "profile.yaml").exists()
    profile = yaml.safe_load((home / "profile.yaml").read_text())
    assert profile["highest_degree_level"] == "bachelors"
    assert any("Python" in s for s in profile["skills"])


def test_resume_add_will_not_clobber_an_edited_profile(home):
    """profile.yaml is the user's after the first parse; re-adding must not overwrite it."""
    (home / "profile.yaml").write_text("name: Hand Edited\nskills: [Fortran]\n", encoding="utf-8")
    result = invoke("resume", "add", str(home / "resume.md"))
    assert result.exit_code == 0
    assert "not overwriting" in result.stdout
    assert "Fortran" in (home / "profile.yaml").read_text()


def test_resume_add_rejects_an_unsupported_format(home):
    bad = home / "resume.rtf"
    bad.write_text("nope", encoding="utf-8")
    result = invoke("resume", "add", str(bad))
    assert result.exit_code == 1


def test_resume_add_reports_a_missing_file(home):
    assert invoke("resume", "add", str(home / "nope.pdf")).exit_code == 1


def test_resume_list(home):
    assert "resume.md" in invoke("resume", "list").stdout


# --- boards ----------------------------------------------------------------------------


def test_board_add_from_a_url(home):
    result = invoke("board", "add", "https://boards.greenhouse.io/anduril")
    assert result.exit_code == 0
    assert "anduril" in invoke("board", "list").stdout


def test_board_add_is_idempotent(home):
    invoke("board", "add", "https://jobs.lever.co/scaleco")
    result = invoke("board", "add", "https://jobs.lever.co/scaleco")
    assert "Already registered" in result.stdout


def test_board_add_rejects_an_unrecognized_url_without_a_source(home):
    result = invoke("board", "add", "https://careers.example.com/jobs")
    assert result.exit_code == 1
    assert "--source" in result.stdout


# --- the queue -------------------------------------------------------------------------


def test_queue_list_shows_the_slate(seeded):
    output = invoke("queue", "list").stdout
    assert "Flight Autonomy" in output or "Embedded" in output
    assert "/day target" in output


def test_queue_show_explains_the_score(seeded):
    """The 'why is this here' output is what stops the queue becoming a rubber stamp."""
    output = invoke("queue", "show", str(queued_id(seeded))).stdout
    assert "Why this is here" in output
    assert "role_family" in output
    assert "Online assessment" in output


def test_queue_show_404s_cleanly(seeded):
    assert invoke("queue", "show", "9999").exit_code == 1


def test_queue_filtered_gives_a_reason_for_each(seeded):
    output = invoke("queue", "filtered").stdout
    assert "below floor" in output or "already applied" in output


def test_approve_then_ready_then_submitted(seeded):
    entry_id = str(queued_id(seeded))
    approve = invoke("queue", "approve", entry_id, "--no-open")
    assert approve.exit_code == 0
    assert "Approved" in approve.stdout

    assert entry_id in invoke("ready").stdout

    submitted = invoke("submitted", entry_id, "--channel", "greenhouse")
    assert submitted.exit_code == 0
    assert "Logged" in submitted.stdout
    assert "Acme" in invoke("app", "log").stdout


def test_approve_does_not_record_a_submission(seeded):
    """Approving prepares. Constraint 1, from the surface a person actually types."""
    entry_id = str(queued_id(seeded))
    invoke("queue", "approve", entry_id, "--no-open")
    conn = connect()
    assert conn.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"] == 0
    row = conn.execute("SELECT state, submitted_at FROM queue_entries WHERE id=?",
                       (entry_id,)).fetchone()
    conn.close()
    assert row["state"] == "approved"
    assert row["submitted_at"] is None


def test_submitted_requires_a_prior_approval(seeded):
    """You cannot skip the review step, even from the CLI."""
    result = invoke("submitted", str(queued_id(seeded)))
    assert result.exit_code == 1


def test_unapprove_returns_an_entry_to_the_queue(seeded):
    entry_id = str(queued_id(seeded))
    invoke("queue", "approve", entry_id, "--no-open")
    assert invoke("queue", "unapprove", entry_id).exit_code == 0
    conn = connect()
    state = conn.execute("SELECT state FROM queue_entries WHERE id=?", (entry_id,)).fetchone()[0]
    conn.close()
    assert state == "queued"


def test_reject_records_the_reason(seeded):
    entry_id = str(queued_id(seeded))
    assert invoke("queue", "reject", entry_id, "wrong_location").exit_code == 0
    conn = connect()
    row = conn.execute("SELECT state, rejection_reason FROM queue_entries WHERE id=?",
                       (entry_id,)).fetchone()
    conn.close()
    assert row["state"] == "rejected"
    assert row["rejection_reason"] == "wrong_location"


def test_reject_refuses_an_unknown_reason(seeded):
    result = invoke("queue", "reject", str(queued_id(seeded)), "because-i-said-so")
    assert result.exit_code == 1
    assert "wrong_location" in result.stdout  # lists the valid ones


def test_snooze(seeded):
    assert invoke("queue", "snooze", str(queued_id(seeded)), "--days", "2").exit_code == 0


def test_paste_upgrades_a_link_only_entry(seeded, tmp_path):
    conn = connect()
    row = conn.execute(
        "SELECT id FROM queue_entries WHERE completeness IN ('partial','link_only') LIMIT 1"
    ).fetchone()
    conn.close()
    description = tmp_path / "desc.txt"
    description.write_text("Deep Kubernetes and Docker work. You will own our Go services.")
    result = invoke("queue", "paste", str(row["id"]), "--file", str(description))
    assert result.exit_code == 0
    assert "high confidence" in result.stdout


def test_paste_rejects_an_empty_description(seeded, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("   ")
    assert invoke("queue", "paste", str(queued_id(seeded)), "--file", str(empty)).exit_code == 1


# --- the application log ---------------------------------------------------------------


def _submit_one(home: Path) -> str:
    entry_id = str(queued_id(home))
    invoke("queue", "approve", entry_id, "--no-open")
    invoke("submitted", entry_id, "--channel", "greenhouse")
    conn = connect()
    app_id = conn.execute("SELECT id FROM applications ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()
    return str(app_id)


def test_app_update_records_an_assessment(seeded):
    app_id = _submit_one(seeded)
    assert invoke("app", "update", app_id, "--oa", "--platform", "HackerRank").exit_code == 0
    conn = connect()
    row = conn.execute("SELECT oa_received, oa_platform FROM applications WHERE id=?",
                       (app_id,)).fetchone()
    conn.close()
    assert row["oa_received"] == 1
    assert row["oa_platform"] == "HackerRank"


def test_app_update_rejects_an_unknown_outcome(seeded):
    assert invoke("app", "update", _submit_one(seeded), "--outcome", "vibes").exit_code == 1


def test_app_update_with_nothing_to_change_is_an_error(seeded):
    assert invoke("app", "update", _submit_one(seeded)).exit_code == 1


def test_export_writes_an_excel_safe_csv(seeded, tmp_path):
    _submit_one(seeded)
    out = tmp_path / "apps.csv"
    result = invoke("export", "--out", str(out))
    assert result.exit_code == 0
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "Company" in out.read_text(encoding="utf-8-sig")


def test_export_rejects_an_unknown_format(seeded, tmp_path):
    assert invoke("export", "--out", str(tmp_path / "x"), "--format", "pdf").exit_code == 1


def test_status_counts_every_state(seeded):
    output = invoke("status").stdout
    for state in ("queued", "filtered", "approved", "submitted"):
        assert state in output

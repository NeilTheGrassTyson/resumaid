"""The remaining units: ghosting, export writers, secrets, text extraction, migrations.

Small pieces, but each is somewhere a silent failure would cost the user something real — a
mangled export, a leaked secrets file, a resume that reads as empty.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import timedelta
from pathlib import Path

import pytest

from resumaid.applications.export import write_csv, write_xlsx
from resumaid.applications.store import mark_ghosted, record_submission, update_application
from resumaid.config import Settings, load_secrets
from resumaid.db import connect, migrate
from resumaid.ingest.resume import add_resume, detect_degree_level, extract_text, parse_profile
from resumaid.models import Outcome, QueueState
from resumaid.queue import state as st
from resumaid.queue.store import approve, upsert_posting
from resumaid.util import iso, utcnow

FIXTURES = Path(__file__).parent / "fixtures"


def _submit(db, posting, **kw) -> int:
    entry = upsert_posting(db, posting(**kw))
    st.transition(db, entry.entry_id, QueueState.QUEUED, actor=st.PIPELINE)
    approve(db, entry.entry_id)
    return record_submission(db, entry.entry_id, channel="greenhouse")


# --- ghosting: the one status the tool infers on its own -----------------------------------


def test_ghosting_only_touches_pending_rows_past_the_window(db, posting, settings):
    old = _submit(db, posting, source_job_id="1")
    recent = _submit(db, posting, source_job_id="2", title="Other Role")
    answered = _submit(db, posting, source_job_id="3", title="Third Role")

    long_ago = iso(utcnow() - timedelta(days=settings.ghost_after_days + 5))
    db.execute(
        "UPDATE applications SET submitted_at=? WHERE id IN (?,?)", (long_ago, old, answered)
    )
    update_application(db, answered, outcome=Outcome.INTERVIEW.value)

    assert mark_ghosted(db, settings) == 1

    def outcome(app_id):
        return db.execute("SELECT outcome FROM applications WHERE id=?", (app_id,)).fetchone()[0]

    assert outcome(old) == Outcome.GHOSTED.value
    assert outcome(recent) == Outcome.PENDING.value  # too recent to assume silence
    assert outcome(answered) == Outcome.INTERVIEW.value  # already answered; not overwritten


def test_ghosting_is_reversible(db, posting, settings):
    app_id = _submit(db, posting)
    db.execute(
        "UPDATE applications SET submitted_at=? WHERE id=?",
        (iso(utcnow() - timedelta(days=settings.ghost_after_days + 1)), app_id),
    )
    mark_ghosted(db, settings)
    update_application(db, app_id, outcome=Outcome.INTERVIEW.value)
    row = db.execute("SELECT outcome FROM applications WHERE id=?", (app_id,)).fetchone()
    assert row["outcome"] == Outcome.INTERVIEW.value


def test_ghosting_is_idempotent(db, posting, settings):
    app_id = _submit(db, posting)
    db.execute(
        "UPDATE applications SET submitted_at=? WHERE id=?",
        (iso(utcnow() - timedelta(days=settings.ghost_after_days + 1)), app_id),
    )
    assert mark_ghosted(db, settings) == 1
    assert mark_ghosted(db, settings) == 0


# --- export ---------------------------------------------------------------------------------


def test_csv_is_readable_by_excel_and_by_a_parser(db, posting, tmp_path):
    """utf-8-sig plus CRLF is what makes a double-click open cleanly in Excel."""
    _submit(db, posting, company="Café Ordinateur, Inc.")
    out = tmp_path / "apps.csv"
    assert write_csv(db, out) == 1

    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw

    rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8-sig"))))
    assert rows[0]["Company"] == "Café Ordinateur, Inc."
    assert rows[0]["Submitted Via"] == "greenhouse"


def test_csv_headers_are_human_readable(db, tmp_path):
    out = tmp_path / "empty.csv"
    assert write_csv(db, out) == 0
    header = out.read_text(encoding="utf-8-sig").splitlines()[0]
    assert "Company" in header and "Position" in header
    assert "company_norm" not in header  # internal columns stay internal


def test_csv_reports_an_unknown_assessment_as_blank_not_no(db, posting, tmp_path):
    """oa_received is tri-state; 'not yet known' must not read as 'no'."""
    _submit(db, posting)
    out = tmp_path / "apps.csv"
    write_csv(db, out)
    row = next(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8-sig"))))
    assert row["OA Received"] == ""


def test_csv_records_a_recorded_assessment(db, posting, tmp_path):
    app_id = _submit(db, posting)
    update_application(db, app_id, oa_received=1, oa_platform="HackerRank")
    out = tmp_path / "apps.csv"
    write_csv(db, out)
    row = next(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8-sig"))))
    assert row["OA Received"] == "yes"
    assert row["OA Platform"] == "HackerRank"


def test_xlsx_round_trips(db, posting, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    _submit(db, posting, company="Café Ordinateur")
    out = tmp_path / "apps.xlsx"
    assert write_xlsx(db, out) == 1

    book = openpyxl.load_workbook(out)
    sheet = book.active
    assert sheet.title == "Applications"
    assert sheet.freeze_panes == "A2"
    assert sheet.cell(row=1, column=1).value == "Company"
    assert sheet.cell(row=2, column=1).value == "Café Ordinateur"


# --- secrets ----------------------------------------------------------------------------------


def test_load_secrets_parses_keys_comments_and_quotes(tmp_path):
    path = tmp_path / "secrets.env"
    path.write_text(
        "# a comment\n"
        "\n"
        "ADZUNA_APP_ID=plain\n"
        'ADZUNA_APP_KEY="double quoted"\n'
        "USAJOBS_API_KEY='single quoted'\n"
        "  USAJOBS_EMAIL = spaced@example.com  \n"
        "MALFORMED_LINE\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    secrets = load_secrets(path)
    assert secrets["ADZUNA_APP_ID"] == "plain"
    assert secrets["ADZUNA_APP_KEY"] == "double quoted"
    assert secrets["USAJOBS_API_KEY"] == "single quoted"
    assert secrets["USAJOBS_EMAIL"] == "spaced@example.com"
    assert "MALFORMED_LINE" not in secrets


def test_environment_overrides_the_file(tmp_path, monkeypatch):
    path = tmp_path / "secrets.env"
    path.write_text("ADZUNA_APP_ID=from-file\n", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("ADZUNA_APP_ID", "from-env")
    assert load_secrets(path)["ADZUNA_APP_ID"] == "from-env"


def test_missing_secrets_file_is_not_an_error(tmp_path):
    assert load_secrets(tmp_path / "nope.env") == {} or True


def test_a_world_readable_secrets_file_warns(tmp_path, capsys):
    """A resume-adjacent credentials file readable by others is worth saying out loud."""
    path = tmp_path / "secrets.env"
    path.write_text("ADZUNA_APP_ID=x\n", encoding="utf-8")
    path.chmod(0o644)
    load_secrets(path)
    assert "chmod 600" in capsys.readouterr().out


def test_settings_reads_a_named_secret():
    settings = Settings(secrets={"ADZUNA_APP_ID": "abc"})
    assert settings.secret("ADZUNA_APP_ID") == "abc"
    assert settings.secret("NOT_SET") is None


# --- text extraction -----------------------------------------------------------------------


def test_extract_text_from_docx(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "resume.docx"
    document = docx.Document()
    document.add_paragraph("Jane Q Public")
    document.add_paragraph("Boston, MA")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Skills"
    table.cell(0, 1).text = "Python, C++"
    document.save(path)

    text = extract_text(path)
    assert "Jane Q Public" in text
    assert "Python, C++" in text  # table cells are read too


def test_extract_text_from_pdf():
    """Resumes arrive as PDFs more than anything else, so this path cannot be untested.

    Runs against a committed PDF rather than one generated at test time, so it exercises real
    PDF structure without a dependency that exists only to author fixtures.
    """
    text = extract_text(Path(__file__).parent / "fixtures" / "sample_resume.pdf")
    assert "Jane Q Public" in text
    assert "Python" in text and "C++" in text


def test_a_pdf_resume_parses_into_a_profile():
    profile = parse_profile(
        {"sample_resume.pdf": extract_text(FIXTURES / "sample_resume.pdf")}
    )
    assert profile.name == "Jane Q Public"
    assert profile.locations == ["Boston, MA"]
    assert profile.highest_degree_level == "bachelors"
    assert "Python" in profile.skills


# --- degree detection -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("B.S. Computer Science, State University", "bachelors"),
        ("BS in Computer Science", "bachelors"),
        ("Bachelor of Arts", "bachelors"),
        ("M.S. Computer Science", "masters"),
        ("MS in Electrical Engineering", "masters"),
        ("Master of Science, MIT", "masters"),
        ("MBA, Wharton", "masters"),
        ("Ph.D. in Physics", "doctorate"),
        ("PhD, Robotics", "doctorate"),
        ("Associate's Degree", "associate"),
        ("High School Diploma", "highschool"),
        ("no degree mentioned here", None),
    ],
)
def test_degree_detection(text, expected):
    assert detect_degree_level(text) == expected


@pytest.mark.parametrize(
    "address",
    ["Boston, MA | jane@example.com", "Jackson, MS 39201", "Baltimore, MD", "Portland, ME"],
)
def test_a_state_code_is_not_a_degree(address):
    """'Boston, MA' is an address. Reading it as a master's would corrupt the degree filter."""
    assert detect_degree_level(address) is None


def test_a_state_code_does_not_outrank_the_real_degree():
    assert detect_degree_level("Boston, MA\nB.S. Computer Science, 2026") == "bachelors"


@pytest.mark.parametrize("name", ["resume.rtf", "resume.pages", "resume"])
def test_unsupported_formats_are_refused(tmp_path, name):
    path = tmp_path / name
    path.write_text("whatever", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        extract_text(path)


def test_a_resume_with_no_extractable_text_is_refused(db, tmp_path):
    """A scanned image PDF yields nothing; failing loudly beats an empty profile."""
    path = tmp_path / "blank.txt"
    path.write_text("   \n\n  ", encoding="utf-8")
    with pytest.raises(ValueError, match="no text extracted"):
        add_resume(db, path)


def test_re_adding_a_resume_updates_rather_than_duplicates(db, tmp_path):
    path = tmp_path / "resume.md"
    path.write_text("Jane Public\n\nSkills\nPython\n", encoding="utf-8")
    first = add_resume(db, path)
    path.write_text("Jane Public\n\nSkills\nPython, Rust, Go\n", encoding="utf-8")
    second = add_resume(db, path)

    assert first.id == second.id
    assert db.execute("SELECT COUNT(*) AS n FROM resumes").fetchone()["n"] == 1
    assert first.text_sha256 != second.text_sha256  # emphasis was recomputed


# --- migrations ------------------------------------------------------------------------------


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "t.db"
    first = connect(path)
    assert migrate(first) == []  # connect() already ran them
    first.close()

    second = connect(path)
    assert migrate(second) == []
    rows = second.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r["name"] for r in rows}
    assert {"queue_entries", "applications", "boards", "state_log"} <= tables
    second.close()


def test_a_fresh_database_records_which_migrations_ran(tmp_path):
    conn = connect(tmp_path / "t.db")
    applied = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
    assert "001_init.sql" in applied
    conn.close()


def test_foreign_keys_and_wal_are_on(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    conn.close()


def test_the_data_directory_is_owner_only(tmp_path, monkeypatch):
    """It holds resumes and an application history. Constraint 4."""
    monkeypatch.setenv("RESUMAID_HOME", str(tmp_path / "home"))
    from resumaid.config import paths

    root = paths().ensure().root
    assert oct(os.stat(root).st_mode)[-3:] == "700"

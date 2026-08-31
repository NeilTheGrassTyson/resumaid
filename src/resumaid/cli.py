"""The command line. Every mutating command is the twin of an API route, calling the same
service function, so the loop is scriptable and testable without a browser (ADR 0002).
"""

from __future__ import annotations

import sqlite3
import sys
import webbrowser
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from resumaid import run as run_mod
from resumaid.applications import export as export_mod
from resumaid.applications.store import (
    list_applications,
    mark_ghosted,
    record_submission,
    stats,
    update_application,
)
from resumaid.config import Settings, paths
from resumaid.db import connect
from resumaid.ingest.interests import (
    load_interests,
    load_profile,
    save_profile,
    write_interests_template,
)
from resumaid.ingest.resume import add_resume, list_resumes, parse_profile, resume_texts
from resumaid.models import Interests, Outcome, Profile, QueueState, RejectionReason, Source
from resumaid.queue import store as queue_store
from resumaid.sources.registry import board_from_url, list_boards, register
from resumaid.util import jload

app = typer.Typer(help="Personal job-search copilot. Finds and prepares; you approve and submit.",
                  no_args_is_help=True)
resume_app = typer.Typer(help="Manage the resumes you maintain.", no_args_is_help=True)
queue_app = typer.Typer(help="Review the queue.", no_args_is_help=True)
board_app = typer.Typer(help="ATS boards to poll.", no_args_is_help=True)
app_log = typer.Typer(help="Your application history.", no_args_is_help=True)
app.add_typer(resume_app, name="resume")
app.add_typer(queue_app, name="queue")
app.add_typer(board_app, name="board")
app.add_typer(app_log, name="app")

console = Console()


def _db() -> sqlite3.Connection:
    return connect()


def _settings() -> Settings:
    settings = Settings()
    try:
        interests = load_interests()
        settings.submissions_per_day = interests.throughput.submissions_per_day
    except FileNotFoundError:
        pass
    return settings


def _require_setup() -> tuple[Profile, Interests]:
    try:
        return load_profile(), load_interests()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def _fmt_score(row: sqlite3.Row) -> str:
    if row["fit_score"] is None:
        return "—"
    marker = {"high": "", "medium": " ~", "low": " ?"}[row["score_confidence"]]
    return f"{row['fit_score']:.0f}{marker}"


# --- setup ---------------------------------------------------------------------------


@app.command()
def init() -> None:
    """Create ~/.resumaid and an interests.yaml to fill in."""
    p = paths().ensure()
    created = write_interests_template()
    connect()
    console.print(f"[green]Ready.[/green] Data directory: {p.root}")
    console.print(f"Now edit [bold]{created}[/bold] — declare the role families, locations, and")
    console.print("filters you want. Nothing is assumed; targeting comes entirely from you.")
    console.print("\nThen: [bold]resumaid resume add <file>[/bold], "
                  "then [bold]resumaid run[/bold].")


@resume_app.command("add")
def resume_add(
    path: Path = typer.Argument(..., help="A .pdf, .docx, .md or .txt resume."),
    master: bool = typer.Option(False, "--master", help="This is your full master resume."),
    reparse: bool = typer.Option(True, help="Refresh profile.yaml from all resumes."),
    force: bool = typer.Option(False, "--force", help="Overwrite an edited profile.yaml."),
) -> None:
    """Register a resume. The file stays where it is; only its text is stored."""
    conn = _db()
    try:
        doc = add_resume(conn, path, is_master=master)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Added[/green] {doc.filename} — {doc.emphasis_summary}")

    if not reparse:
        return
    target = paths().profile
    if target.exists() and not force:
        console.print(f"[yellow]{target} exists and is yours to edit; not overwriting.[/yellow]")
        console.print("Pass --force to re-parse from scratch.")
        return
    profile = parse_profile(resume_texts(conn))
    save_profile(profile)
    console.print(f"Parsed profile -> [bold]{target}[/bold]")
    console.print(
        f"  {len(profile.skills)} skills, {len(profile.employment)} roles, "
        f"degree: {profile.highest_degree_level or 'unknown'}"
    )
    console.print("[dim]Review and correct it — the parse is a starting point, "
                  "not an authority.[/dim]")


@resume_app.command("list")
def resume_list() -> None:
    """Show the resumes the tool will select among."""
    docs = list_resumes(_db())
    if not docs:
        console.print("No resumes yet. [bold]resumaid resume add <file>[/bold]")
        return
    table = Table("id", "file", "master", "emphasis")
    for doc in docs:
        table.add_row(str(doc.id), doc.filename, "yes" if doc.is_master else "",
                      ", ".join(doc.emphasis_terms[:6]))
    console.print(table)


# --- boards --------------------------------------------------------------------------


@board_app.command("add")
def board_add(
    target: str = typer.Argument(..., help="A board URL, or a token with --source."),
    source: str | None = typer.Option(None, help="greenhouse | lever | ashby"),
    company: str | None = typer.Option(None, help="Display name."),
) -> None:
    """Register an ATS board to poll directly."""
    conn = _db()
    ref = board_from_url(target)
    if ref is None:
        if not source:
            console.print("[red]Not a recognized board URL. Pass --source with a token.[/red]")
            raise typer.Exit(1)
        added = register(conn, Source(source), target, company=company, via="manual")
        console.print(("[green]Added[/green] " if added else "Already registered: ")
                      + f"{source}/{target}")
        return
    added = register(conn, ref.source, ref.token, company=company, via="manual")
    console.print(("[green]Added[/green] " if added else "Already registered: ")
                  + f"{ref.source.value}/{ref.token}")


@board_app.command("list")
def board_list() -> None:
    """Boards being polled, including ones discovered automatically."""
    rows = list_boards(_db(), enabled_only=False)
    if not rows:
        console.print("No boards yet. They appear automatically as aggregators surface them,")
        console.print("or add one: [bold]resumaid board add <url>[/bold]")
        return
    table = Table("source", "token", "company", "found via", "last polled", "status")
    for row in rows:
        table.add_row(row["source"], row["token"], row["company"] or "",
                      row["discovered_via"] or "", (row["last_polled_at"] or "")[:10],
                      row["last_status"] or "")
    console.print(table)


# --- the run -------------------------------------------------------------------------


@app.command("run")
def run_cmd(
    llm: bool = typer.Option(False, "--llm", help="Adjudicate near-the-bar roles with an LLM."),
    research_oa: bool = typer.Option(False, "--research-oa", help="Use cached company research."),
) -> None:
    """Discover, score, and queue. Never submits anything."""
    profile, interests = _require_setup()
    conn = _db()
    with console.status("Polling permitted sources…"):
        report = run_mod.execute(conn, profile, interests, _settings(),
                                 use_llm=llm, use_research=research_oa)
    console.print(f"[green]Run complete.[/green] {report.summary()}")
    for err in report.errors[:5]:
        console.print(f"  [yellow]{err}[/yellow]")
    if report.queued:
        console.print("\nReview them: [bold]resumaid queue list[/bold] "
                      "or [bold]resumaid serve[/bold]")


# --- the queue -----------------------------------------------------------------------


@queue_app.command("list")
def queue_list(
    limit: int | None = typer.Option(None, help="Override the daily slate size."),
) -> None:
    """Today's slate, ranked."""
    conn = _db()
    settings = _settings()
    rows = queue_store.slate(conn, settings, limit)
    if not rows:
        counts = queue_store.counts_by_state(conn)
        console.print("[yellow]Nothing queued.[/yellow]")
        if counts.get("filtered"):
            console.print(f"  {counts['filtered']} filtered out — "
                          "[bold]resumaid queue filtered[/bold]")
        else:
            console.print("  Run [bold]resumaid run[/bold] first.")
        return
    table = Table("id", "score", "role", "company", "location", "OA", "resume")
    for row in rows:
        locations = jload(row["locations"], []) or []
        resume = ""
        if row["recommended_resume_id"]:
            got = conn.execute("SELECT filename FROM resumes WHERE id=?",
                               (row["recommended_resume_id"],)).fetchone()
            resume = got["filename"] if got else ""
        oa = {"likely": "likely", "possible": "maybe", "unlikely": "", "unknown": "?"}[
            row["oa_expected"]]
        table.add_row(str(row["id"]), _fmt_score(row), row["title"][:38], row["company"][:22],
                      (locations[0] if locations else "")[:18], oa, resume[:20])
    console.print(table)
    console.print(f"[dim]{len(rows)} of {settings.submissions_per_day}/day target. "
                  "~ = snippet only, ? = link only.[/dim]")


@queue_app.command("show")
def queue_show(entry_id: int) -> None:
    """Everything about one entry, including why it scored what it did."""
    conn = _db()
    row = queue_store.get(conn, entry_id)
    if row is None:
        console.print(f"[red]No entry {entry_id}[/red]")
        raise typer.Exit(1)
    locations = jload(row["locations"], []) or []
    where = ", ".join(locations) or "location unspecified"
    console.print(Panel(
        f"[bold]{row['title']}[/bold]\n{row['company']} — {where}\n{row['apply_url']}",
        title=f"#{row['id']}  {row['state']}",
    ))
    if row["provenance_note"]:
        console.print(f"[dim]{row['provenance_note']}[/dim]\n")

    breakdown = jload(row["score_breakdown"], None)
    if breakdown:
        table = Table("dimension", "score", "weight", "why", title="Why this is here")
        for dim in breakdown.get("dimensions", []):
            table.add_row(dim["name"], f"{dim['score']:.0f}", f"{dim['weight']}", dim["evidence"])
        console.print(table)
        if breakdown.get("adjudication_note"):
            console.print(f"[cyan]LLM: {breakdown['adjudication_note']}[/cyan]")
        for missing in breakdown.get("missing_signals", []):
            console.print(f"  [yellow]missing:[/yellow] {missing}")

    if row["recommended_resume_id"]:
        console.print(f"\n[green]Resume:[/green] {row['selection_rationale']}")
    evidence = jload(row["oa_expectation_evidence"], []) or []
    console.print(f"[bold]Online assessment:[/bold] {row['oa_expected']} "
                  f"({row['oa_expectation_confidence']} confidence)")
    for item in evidence:
        console.print(f"  · {item.get('detail')}")

    if row["description_text"]:
        console.print(Panel(row["description_text"][:1500], title="Posting"))
    else:
        console.print("[yellow]No description available from a permitted source.[/yellow]")
        console.print("Paste it in: [bold]resumaid queue paste "
                      f"{row['id']} --file <path>[/bold]")


@queue_app.command("approve")
def queue_approve(
    entry_id: int,
    note: str | None = typer.Option(None),
    open_url: bool = typer.Option(True, "--open/--no-open", help="Open the posting."),
) -> None:
    """Approve for the ready tray. Sends nothing — you submit it yourself."""
    conn = _db()
    row = queue_store.get(conn, entry_id)
    if row is None:
        console.print(f"[red]No entry {entry_id}[/red]")
        raise typer.Exit(1)
    queue_store.approve(conn, entry_id, note)
    console.print(f"[green]Approved[/green] #{entry_id} — {row['title']} at {row['company']}")
    if row["recommended_resume_id"]:
        got = conn.execute("SELECT path FROM resumes WHERE id=?",
                           (row["recommended_resume_id"],)).fetchone()
        if got:
            console.print(f"  Resume: [bold]{got['path']}[/bold]")
    console.print(f"  Apply:  {row['apply_url']}")
    if open_url:
        webbrowser.open(row["apply_url"])
    console.print("\n[dim]When you've actually applied: "
                  f"resumaid submitted {entry_id}[/dim]")


@queue_app.command("reject")
def queue_reject(
    entry_id: int,
    reason: str = typer.Argument(..., help="|".join(r.value for r in RejectionReason)),
    note: str | None = typer.Option(None),
) -> None:
    """Reject, with a reason. The reasons are what make weight tuning honest."""
    try:
        parsed = RejectionReason(reason)
    except ValueError as exc:
        console.print(f"[red]Unknown reason. One of: "
                      f"{', '.join(r.value for r in RejectionReason)}[/red]")
        raise typer.Exit(1) from exc
    queue_store.reject(_db(), entry_id, parsed, note)
    console.print(f"Rejected #{entry_id} ({parsed.value})")


@queue_app.command("snooze")
def queue_snooze(entry_id: int, days: int = typer.Option(3)) -> None:
    """Defer an entry; it returns to the queue when the time is up."""
    queue_store.snooze(_db(), entry_id, days)
    console.print(f"Snoozed #{entry_id} for {days}d")


@queue_app.command("paste")
def queue_paste(
    entry_id: int,
    file: Path | None = typer.Option(None, "--file", help="File holding the description."),
) -> None:
    """Paste a description the tool may not fetch, then re-score at full confidence."""
    if file is not None:
        text = file.read_text(encoding="utf-8")
    else:
        console.print("[dim]Paste the description, then Ctrl-D:[/dim]")
        text = sys.stdin.read()
    conn = _db()
    try:
        queue_store.paste_description(conn, entry_id, text)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    profile, interests = _require_setup()
    from resumaid.match.pipeline import score_and_gate

    score_and_gate(conn, profile, interests, _settings(), list_resumes(conn))
    row = queue_store.get(conn, entry_id)
    console.print(f"[green]Upgraded and re-scored:[/green] fit {row['fit_score']:.0f} "
                  f"({row['score_confidence']} confidence), state {row['state']}")


@queue_app.command("filtered")
def queue_filtered(limit: int = typer.Option(20)) -> None:
    """What the gate removed, and why. Auditing this is how you tune the bar."""
    rows = _db().execute(
        "SELECT * FROM queue_entries WHERE state='filtered'"
        " ORDER BY fit_score DESC NULLS LAST LIMIT ?", (limit,)
    ).fetchall()
    if not rows:
        console.print("Nothing filtered.")
        return
    table = Table("id", "score", "role", "company", "why filtered")
    for row in rows:
        table.add_row(str(row["id"]), _fmt_score(row), row["title"][:34],
                      row["company"][:20], row["filter_reason"] or "")
    console.print(table)


@app.command("ready")
def ready() -> None:
    """Approved and waiting for you to apply."""
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM queue_entries WHERE state='approved' ORDER BY state_changed_at"
    ).fetchall()
    if not rows:
        console.print("Nothing approved yet.")
        return
    table = Table("id", "role", "company", "resume", "apply at", "approved")
    for row in rows:
        resume = ""
        if row["recommended_resume_id"]:
            got = conn.execute("SELECT path FROM resumes WHERE id=?",
                               (row["recommended_resume_id"],)).fetchone()
            resume = Path(got["path"]).name if got else ""
        table.add_row(str(row["id"]), row["title"][:30], row["company"][:20], resume[:22],
                      row["apply_url"][:40], row["state_changed_at"][:10])
    console.print(table)
    stale = queue_store.stale_approved(conn, _settings())
    if stale:
        console.print(f"\n[yellow]{len(stale)} approved over 24h ago.[/yellow] "
                      "Did those go out? [bold]resumaid submitted <id>[/bold]")


@app.command("submitted")
def submitted(
    entry_id: int,
    channel: str | None = typer.Option(None, help="greenhouse | workday | company site | …"),
    note: str | None = typer.Option(None),
) -> None:
    """Record that YOU submitted this application.

    The only path to the `submitted` state. The tool never takes it on its own.
    """
    conn = _db()
    try:
        app_id = record_submission(conn, entry_id, channel=channel, note=note)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Logged[/green] as application #{app_id}.")


# --- the application log --------------------------------------------------------------


@app_log.command("log")
def app_list(
    outcome: str | None = typer.Option(None, help="pending | oa | interview | offer | …"),
    company: str | None = typer.Option(None),
) -> None:
    """Where you've applied, when, and what came back."""
    conn = _db()
    mark_ghosted(conn, _settings())
    rows = list_applications(conn, outcome=outcome, company=company)
    if not rows:
        console.print("No applications logged yet.")
        return
    table = Table("id", "company", "position", "submitted", "via", "outcome", "OA")
    for row in rows:
        oa = "—" if row["oa_received"] is None else ("yes" if row["oa_received"] else "no")
        if row["oa_received"] is None and row["oa_expected"] == "likely":
            oa = "expected"
        table.add_row(str(row["id"]), row["company"][:22], row["title"][:30],
                      row["submitted_at"][:10], (row["submission_channel"] or "")[:12],
                      row["outcome"], oa)
    console.print(table)
    counts = stats(conn)
    console.print(f"[dim]{counts['total']} total. "
                  f"OA in {counts['oa_received']}/{counts['oa_known']} where known.[/dim]")


@app_log.command("update")
def app_update(
    app_id: int,
    outcome: str | None = typer.Option(None, help="pending|oa|interview|offer|rejected|…"),
    oa: bool | None = typer.Option(None, "--oa/--no-oa", help="Did an assessment arrive?"),
    platform: str | None = typer.Option(None, help="HackerRank, CodeSignal, …"),
    note: str | None = typer.Option(None),
) -> None:
    """Record what came back. Answering --oa/--no-oa is what teaches the OA prediction."""
    fields: dict[str, object] = {}
    if outcome:
        try:
            fields["outcome"] = Outcome(outcome).value
        except ValueError as exc:
            console.print(f"[red]Unknown outcome {outcome!r}[/red]")
            raise typer.Exit(1) from exc
    if oa is not None:
        fields["oa_received"] = int(oa)
    if platform:
        fields["oa_platform"] = platform
    if note:
        fields["notes"] = note
    if not fields:
        console.print("[yellow]Nothing to update.[/yellow]")
        raise typer.Exit(1)
    update_application(_db(), app_id, **fields)
    console.print(f"[green]Updated[/green] application #{app_id}")


@app.command("export")
def export(
    out: Path = typer.Option(Path("applications.csv"), "--out", "-o"),
    fmt: str = typer.Option("csv", "--format", help="csv | xlsx"),
) -> None:
    """Export the application history. CSV opens in Excel with dates and accents intact."""
    conn = _db()
    if fmt == "csv":
        n = export_mod.write_csv(conn, out)
    elif fmt == "xlsx":
        try:
            n = export_mod.write_xlsx(conn, out)
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
    else:
        console.print("[red]--format must be csv or xlsx[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Wrote {n} applications[/green] -> {out}")


@app.command()
def status() -> None:
    """Where everything stands."""
    conn = _db()
    counts = queue_store.counts_by_state(conn)
    table = Table("state", "count")
    for state in QueueState:
        table.add_row(state.value, str(counts.get(state.value, 0)))
    console.print(table)
    console.print(f"Resumes: {len(list_resumes(conn))}  Boards: {len(list_boards(conn))}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Localhost only. This is a single-user tool."),
    port: int = typer.Option(8765),
) -> None:
    """Open the review UI."""
    import uvicorn

    console.print(f"Review queue: [bold]http://{host}:{port}[/bold]")
    uvicorn.run("resumaid.api.app:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()

"""Scoring and gating a batch of discovered postings.

Order matters: gate first (cheap, and constraint 5 wants low-fit roles removed rather than
ranked low), then score the survivors, then adjudicate only what lands near the bar.

This module never transitions anything to `approved` or `submitted`. Those are human actions.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from resumaid.applications import oa as oa_mod
from resumaid.applications.store import save_oa_assessment
from resumaid.config import Settings
from resumaid.match import gate as gate_mod
from resumaid.match import llm as llm_mod
from resumaid.match import ranker, resume_select
from resumaid.match.scorer import score
from resumaid.models import (
    Completeness,
    Confidence,
    DatePrecision,
    Interests,
    Profile,
    QueueState,
    RawPosting,
    ResumeDoc,
    Source,
)
from resumaid.queue import state as st
from resumaid.queue.store import age_days
from resumaid.util import iso, jdump, jload, parse_iso, utcnow


@dataclass
class ScoreSummary:
    scored: int = 0
    queued: int = 0
    filtered: int = 0
    adjudicated: int = 0


def _row_to_posting(row: sqlite3.Row) -> RawPosting:
    return RawPosting(
        source=Source(row["source"]),
        source_job_id=row["source_job_id"],
        company=row["company"],
        title=row["title"],
        locations=jload(row["locations"], []) or [],
        remote=bool(row["remote"]),
        posted_at=parse_iso(row["posted_at"]),
        posted_at_precision=DatePrecision(row["posted_at_precision"]),
        apply_url=row["apply_url"],
        department=row["department"],
        employment_type=row["employment_type"],
        compensation=row["compensation"],
        description_text=row["description_text"],
        completeness=Completeness(row["completeness"]),
        provenance_note=row["provenance_note"],
    )


def score_and_gate(
    conn: sqlite3.Connection,
    profile: Profile,
    interests: Interests,
    settings: Settings,
    resumes: list[ResumeDoc],
    *,
    use_llm: bool = False,
    use_research: bool = False,
) -> ScoreSummary:
    """Score every unscored entry, then queue or filter it."""
    summary = ScoreSummary()
    rows = conn.execute(
        "SELECT * FROM queue_entries WHERE scored_at IS NULL AND state IN (?, ?, ?)",
        (QueueState.DISCOVERED.value, QueueState.QUEUED.value, QueueState.FILTERED.value),
    ).fetchall()

    for row in rows:
        posting = _row_to_posting(row)
        summary.scored += 1

        result = gate_mod.evaluate(conn, posting, profile, interests)
        breakdown = score(posting, profile, interests, result.results)
        fit = breakdown.fit_score

        floor = gate_mod.floor_for(breakdown.role_family, interests, settings.fit_floor)

        # Adjudicate only near the bar, where judgment changes the outcome (ADR 0006).
        if result.passed and use_llm and abs(fit - floor) <= settings.adjudication_band:
            verdict = llm_mod.adjudicate(posting, profile, settings.secret("ANTHROPIC_API_KEY"))
            if verdict is not None:
                fit = max(0.0, min(100.0, fit + verdict.adjustment))
                breakdown.adjudicated = True
                breakdown.adjudication_note = f"{verdict.verdict}: {verdict.reason}"
                summary.adjudicated += 1

        confidence = Confidence(row["score_confidence"])
        rank, recency, recency_note = ranker.rank_score(
            fit, age_days(row), posting.posted_at_precision, confidence, settings
        )
        breakdown.matched_signals.append(recency_note)

        selection = resume_select.select(posting, resumes)

        conn.execute(
            """UPDATE queue_entries SET fit_score = ?, score_breakdown = ?, recency_factor = ?,
                   rank_score = ?, scored_at = ?, recommended_resume_id = ?,
                   selection_rationale = ?, runner_up_resume_id = ?
               WHERE id = ?""",
            (fit, jdump(breakdown.model_dump()), recency, rank, iso(utcnow()),
             selection.resume_id, selection.rationale, selection.runner_up_id, row["id"]),
        )

        assessment = oa_mod.assess(
            conn, company=posting.company, description_text=posting.description_text,
            use_research=use_research,
        )
        save_oa_assessment(conn, row["id"], assessment)

        current = QueueState(row["state"])
        if not result.passed:
            if current is not QueueState.FILTERED:
                st.transition(conn, row["id"], QueueState.FILTERED, actor=st.PIPELINE,
                              note=result.reason,
                              extra={"filter_reason": result.detail or result.reason})
            summary.filtered += 1
        elif fit < floor:
            reason = f"fit {fit:.0f} below floor {floor:.0f}"
            if current is not QueueState.FILTERED:
                st.transition(conn, row["id"], QueueState.FILTERED, actor=st.PIPELINE,
                              note="below_fit_floor", extra={"filter_reason": reason})
            summary.filtered += 1
        else:
            if current is QueueState.DISCOVERED or current is QueueState.FILTERED:
                st.transition(conn, row["id"], QueueState.QUEUED, actor=st.PIPELINE,
                              extra={"filter_reason": None})
            summary.queued += 1

    return summary

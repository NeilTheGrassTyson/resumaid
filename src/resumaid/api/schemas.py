"""Response and request shapes.

These are what `openapi-typescript` turns into `ui/src/api/types.ts`, so the SPA's types come
from here rather than being maintained twice (ADR 0002).
"""

from __future__ import annotations

from pydantic import BaseModel

from resumaid.models import (
    DimensionScore,
    OAEvidence,
    Outcome,
    RejectionReason,
)


class ResumeOut(BaseModel):
    id: int
    filename: str
    path: str
    is_master: bool
    emphasis_summary: str


class QueueEntryOut(BaseModel):
    """Every list field here is always populated by the route, so none carry a default:
    an optional field in the schema becomes an optional type in the SPA, which would force
    null-checks against a guarantee the server does keep."""

    id: int
    state: str
    source: str
    company: str
    title: str
    locations: list[str]
    remote: bool
    posted_at: str | None = None
    posted_at_precision: str
    apply_url: str
    department: str | None = None
    compensation: str | None = None
    description_text: str | None = None
    description_source: str | None = None
    completeness: str
    provenance_note: str | None = None
    also_seen_in: list[str]

    fit_score: float | None = None
    score_confidence: str
    rank_score: float | None = None
    recency_factor: float | None = None
    dimensions: list[DimensionScore]
    matched_signals: list[str]
    missing_signals: list[str]
    role_family: str | None = None
    adjudication_note: str | None = None

    oa_expected: str
    oa_expectation_confidence: str
    oa_expectation_evidence: list[OAEvidence]

    recommended_resume: ResumeOut | None = None
    runner_up_resume: ResumeOut | None = None
    selection_rationale: str | None = None

    filter_reason: str | None = None
    state_changed_at: str


class SlateOut(BaseModel):
    entries: list[QueueEntryOut]
    slate_size: int
    submissions_per_day: int
    total_queued: int
    counts: dict[str, int]


class RejectIn(BaseModel):
    reason: RejectionReason
    note: str | None = None


class SnoozeIn(BaseModel):
    days: int = 3


class PasteIn(BaseModel):
    text: str


class ApproveIn(BaseModel):
    note: str | None = None


class SubmitIn(BaseModel):
    """Recording a submission the human already made. The tool never initiates one."""

    channel: str | None = None
    note: str | None = None


class ApplicationOut(BaseModel):
    id: int
    company: str
    title: str
    location: str | None = None
    source: str
    apply_url: str | None = None
    submitted_at: str
    submission_channel: str | None = None
    resume_used: str | None = None
    fit_score_at_submit: float | None = None
    oa_expected: str
    oa_received: bool | None = None
    oa_received_at: str | None = None
    oa_platform: str | None = None
    oa_due_at: str | None = None
    outcome: str
    outcome_at: str | None = None
    notes: str | None = None


class ApplicationUpdateIn(BaseModel):
    outcome: Outcome | None = None
    oa_received: bool | None = None
    oa_platform: str | None = None
    oa_due_at: str | None = None
    notes: str | None = None
    submission_channel: str | None = None


class RunIn(BaseModel):
    use_llm: bool = False
    use_research: bool = False


class RunOut(BaseModel):
    postings_seen: int
    new_entries: int
    queued: int
    filtered: int
    boards_added: int
    expired: int
    errors: list[str]
    summary: str


class StatsOut(BaseModel):
    total: int
    by_outcome: dict[str, int]
    oa_received: int
    oa_known: int

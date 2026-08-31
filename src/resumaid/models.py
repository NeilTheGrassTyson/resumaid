"""Domain models.

The vocabulary of the pipeline. Enums here are the same strings the database stores, so a row
round-trips without a translation layer.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Source(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    ADZUNA = "adzuna"
    USAJOBS = "usajobs"
    MANUAL = "manual"


#: Direct ATS records carry full descriptions, so they win a dedupe tie over aggregators.
SOURCE_PRIORITY: dict[Source, int] = {
    Source.GREENHOUSE: 100,
    Source.LEVER: 95,
    Source.ASHBY: 90,
    Source.USAJOBS: 60,
    Source.ADZUNA: 50,
    Source.MANUAL: 10,
}


class Completeness(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    LINK_ONLY = "link_only"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


#: How much a score is discounted for being built on thin data (REVIEW_QUEUE_SPEC.md §5.2).
CONFIDENCE_FACTOR: dict[Confidence, float] = {
    Confidence.HIGH: 1.00,
    Confidence.MEDIUM: 0.92,
    Confidence.LOW: 0.85,
}

COMPLETENESS_CONFIDENCE: dict[Completeness, Confidence] = {
    Completeness.FULL: Confidence.HIGH,
    Completeness.PARTIAL: Confidence.MEDIUM,
    Completeness.LINK_ONLY: Confidence.LOW,
}


class DatePrecision(StrEnum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    UNKNOWN = "unknown"


class QueueState(StrEnum):
    DISCOVERED = "discovered"
    FILTERED = "filtered"
    QUEUED = "queued"
    APPROVED = "approved"
    REJECTED = "rejected"
    SNOOZED = "snoozed"
    EXPIRED = "expired"
    SUBMITTED = "submitted"


class RejectionReason(StrEnum):
    WRONG_SENIORITY = "wrong_seniority"
    WRONG_LOCATION = "wrong_location"
    WRONG_INDUSTRY = "wrong_industry"
    NOT_THIS_COMPANY = "not_this_company"
    ALREADY_APPLIED = "already_applied"
    STALE_POSTING = "stale_posting"
    COMPENSATION = "compensation"
    OTHER = "other"


class Outcome(StrEnum):
    PENDING = "pending"
    OA = "oa"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    GHOSTED = "ghosted"
    WITHDRAWN = "withdrawn"


class OAExpectation(StrEnum):
    LIKELY = "likely"
    POSSIBLE = "possible"
    UNLIKELY = "unlikely"
    UNKNOWN = "unknown"


class RawPosting(BaseModel):
    """What a source adapter produces, before scoring."""

    source: Source
    source_job_id: str
    company: str
    title: str
    locations: list[str] = Field(default_factory=list)
    remote: bool = False
    posted_at: datetime | None = None
    posted_at_precision: DatePrecision = DatePrecision.UNKNOWN
    apply_url: str
    department: str | None = None
    employment_type: str | None = None
    compensation: str | None = None
    description_text: str | None = None
    completeness: Completeness = Completeness.LINK_ONLY
    provenance_note: str | None = None
    closes_at: date | None = None

    @property
    def confidence(self) -> Confidence:
        return COMPLETENESS_CONFIDENCE[self.completeness]


class DimensionScore(BaseModel):
    """One scored dimension, with the evidence that produced it.

    The evidence is not decoration: an unexplained score trains the user to rubber-stamp the
    queue, which defeats the human-in-the-loop that constraint 1 depends on.
    """

    name: str
    score: float  # 0..100
    weight: float
    evidence: str


class ScoreBreakdown(BaseModel):
    dimensions: list[DimensionScore] = Field(default_factory=list)
    matched_signals: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    hard_filter_results: dict[str, str] = Field(default_factory=dict)
    role_family: str | None = None
    adjudicated: bool = False
    adjudication_note: str | None = None

    @property
    def fit_score(self) -> float:
        total_weight = sum(d.weight for d in self.dimensions)
        if total_weight <= 0:
            return 0.0
        return sum(d.score * d.weight for d in self.dimensions) / total_weight


class OAEvidence(BaseModel):
    kind: str  # "history" | "posting_text" | "research"
    detail: str
    quote: str | None = None


class OAAssessment(BaseModel):
    expected: OAExpectation = OAExpectation.UNKNOWN
    confidence: Confidence = Confidence.LOW
    evidence: list[OAEvidence] = Field(default_factory=list)


class ResumeDoc(BaseModel):
    id: int | None = None
    filename: str
    path: str
    added_at: datetime | None = None
    text_sha256: str = ""
    emphasis_terms: list[str] = Field(default_factory=list)
    emphasis_summary: str = ""
    is_master: bool = False


class Education(BaseModel):
    school: str | None = None
    degree: str | None = None
    degree_level: str | None = None  # highschool|associate|bachelors|masters|doctorate
    field_of_study: str | None = None
    graduation: str | None = None
    source_span: str | None = None


class Employment(BaseModel):
    employer: str | None = None
    title: str | None = None
    start: str | None = None
    end: str | None = None
    source_span: str | None = None


class Profile(BaseModel):
    """The structured resume parse. Written to profile.yaml and hand-editable thereafter."""

    name: str | None = None
    skills: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    employment: list[Employment] = Field(default_factory=list)
    highest_degree_level: str | None = None
    seniority: str | None = None
    locations: list[str] = Field(default_factory=list)
    parsed_from: list[str] = Field(default_factory=list)
    notes: str | None = None


class RoleFamily(BaseModel):
    name: str
    weight: float = 1.0
    keywords: list[str] = Field(default_factory=list)
    min_fit: float | None = None  # per-family floor; reachable, but held to a higher bar


class LocationPrefs(BaseModel):
    remote: bool = True
    metros: list[str] = Field(default_factory=list)
    relocation: str = "no"  # no | willing | preferred

    @field_validator("relocation", mode="before")
    @classmethod
    def _coerce_yaml_bool(cls, v: object) -> object:
        # YAML parses a bare `no` as False and `yes` as True. Writing `relocation: no` is the
        # natural thing to type, so accept it rather than erroring at the user.
        if isinstance(v, bool):
            return "willing" if v else "no"
        return v


class HardFilters(BaseModel):
    degree_level_min: str | None = None
    seniority: list[str] = Field(default_factory=list)
    citizenship_required_ok: bool = True
    clearance_required_ok: bool = False
    employment_types: list[str] = Field(default_factory=list)


class Exclusions(BaseModel):
    companies: list[str] = Field(default_factory=list)
    title_keywords: list[str] = Field(default_factory=list)


class Throughput(BaseModel):
    submissions_per_day: int = 5


class Interests(BaseModel):
    """Declared targeting. Runtime input, never repository configuration."""

    role_families: list[RoleFamily] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    locations: LocationPrefs = Field(default_factory=LocationPrefs)
    hard_filters: HardFilters = Field(default_factory=HardFilters)
    exclusions: Exclusions = Field(default_factory=Exclusions)
    throughput: Throughput = Field(default_factory=Throughput)

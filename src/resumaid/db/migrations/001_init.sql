-- Initial schema. See REVIEW_QUEUE_SPEC.md for what each field means and why.

CREATE TABLE resumes (
    id              INTEGER PRIMARY KEY,
    filename        TEXT NOT NULL,
    path            TEXT NOT NULL UNIQUE,
    added_at        TEXT NOT NULL,
    text_sha256     TEXT NOT NULL,
    raw_text        TEXT NOT NULL,
    emphasis_terms  TEXT NOT NULL DEFAULT '[]',   -- JSON array
    emphasis_summary TEXT NOT NULL DEFAULT '',
    is_master       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE queue_entries (
    id                   INTEGER PRIMARY KEY,

    -- identity and provenance
    source               TEXT NOT NULL,
    source_job_id        TEXT NOT NULL,
    dedupe_key           TEXT NOT NULL,
    first_seen_at        TEXT NOT NULL,
    last_seen_at         TEXT NOT NULL,
    missed_runs          INTEGER NOT NULL DEFAULT 0,
    provenance_note      TEXT,
    also_seen_in         TEXT NOT NULL DEFAULT '[]',  -- JSON array of source names

    -- the posting
    company              TEXT NOT NULL,
    title                TEXT NOT NULL,
    locations            TEXT NOT NULL DEFAULT '[]',  -- JSON array
    remote               INTEGER NOT NULL DEFAULT 0,
    posted_at            TEXT,
    posted_at_precision  TEXT NOT NULL DEFAULT 'unknown',
    closes_at            TEXT,
    apply_url            TEXT NOT NULL,
    department           TEXT,
    employment_type      TEXT,
    compensation         TEXT,
    description_text     TEXT,
    description_source   TEXT,                        -- 'api' | 'human_paste'
    completeness         TEXT NOT NULL DEFAULT 'link_only',

    -- match result
    fit_score            REAL,
    score_breakdown      TEXT,                         -- JSON
    score_confidence     TEXT NOT NULL DEFAULT 'low',
    recency_factor       REAL,
    rank_score           REAL,
    scored_at            TEXT,

    -- online assessment expectation
    oa_expected              TEXT NOT NULL DEFAULT 'unknown',
    oa_expectation_confidence TEXT NOT NULL DEFAULT 'low',
    oa_expectation_evidence  TEXT NOT NULL DEFAULT '[]',  -- JSON array

    -- resume selection (selection, never rewriting)
    recommended_resume_id  INTEGER REFERENCES resumes(id) ON DELETE SET NULL,
    selection_rationale    TEXT,
    runner_up_resume_id    INTEGER REFERENCES resumes(id) ON DELETE SET NULL,

    -- review
    state                TEXT NOT NULL DEFAULT 'discovered',
    state_changed_at     TEXT NOT NULL,
    filter_reason        TEXT,
    decision_note        TEXT,
    rejection_reason     TEXT,
    snooze_until         TEXT,

    -- submission. Written only by a human action; see the trigger below.
    submitted_at         TEXT,
    submission_channel   TEXT,
    confirmation_note    TEXT,

    -- Stage 2 hook. The column exists so the schema is stable; nothing writes it in Stage 1.
    cover_letter_id      INTEGER,

    UNIQUE (source, source_job_id)
);

CREATE INDEX idx_queue_state       ON queue_entries (state);
CREATE INDEX idx_queue_dedupe      ON queue_entries (dedupe_key);
CREATE INDEX idx_queue_rank        ON queue_entries (state, rank_score DESC);
CREATE INDEX idx_queue_company     ON queue_entries (company);

-- The durable application history. Deliberately denormalized: postings get pulled down
-- upstream, and a history that goes blank when a job closes is worthless.
CREATE TABLE applications (
    id                   INTEGER PRIMARY KEY,
    queue_entry_id       INTEGER REFERENCES queue_entries(id) ON DELETE SET NULL,

    company              TEXT NOT NULL,
    title                TEXT NOT NULL,
    company_norm         TEXT NOT NULL,   -- normalized, for the duplicate guard
    title_norm           TEXT NOT NULL,
    location             TEXT,
    source               TEXT NOT NULL,
    apply_url            TEXT,

    submitted_at         TEXT NOT NULL,
    submission_channel   TEXT,
    resume_used          TEXT,
    resume_id            INTEGER REFERENCES resumes(id) ON DELETE SET NULL,
    cover_letter_id      INTEGER,
    fit_score_at_submit  REAL,

    oa_expected              TEXT NOT NULL DEFAULT 'unknown',
    oa_expectation_confidence TEXT NOT NULL DEFAULT 'low',
    oa_expectation_evidence  TEXT NOT NULL DEFAULT '[]',
    oa_received          INTEGER,          -- NULL = not yet known
    oa_received_at       TEXT,
    oa_platform          TEXT,
    oa_due_at            TEXT,
    oa_completed_at      TEXT,

    outcome              TEXT NOT NULL DEFAULT 'pending',
    outcome_at           TEXT,
    last_touched_at      TEXT NOT NULL,
    notes                TEXT
);

CREATE INDEX idx_app_dupe    ON applications (company_norm, title_norm);
CREATE INDEX idx_app_outcome ON applications (outcome);

-- Registered ATS boards, grown automatically from aggregator apply-URLs (ADR 0007).
CREATE TABLE boards (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    token         TEXT NOT NULL,
    company       TEXT,
    added_at      TEXT NOT NULL,
    discovered_via TEXT,             -- 'manual' | 'adzuna' | ...
    last_polled_at TEXT,
    last_status   TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (source, token)
);

-- Cached company research (Sonar). Kept out of the hot path; opt-in per run.
CREATE TABLE company_research (
    company_norm  TEXT PRIMARY KEY,
    oa_verdict    TEXT,
    summary       TEXT,
    fetched_at    TEXT NOT NULL
);

CREATE TABLE runs (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    sources_polled TEXT NOT NULL DEFAULT '[]',
    postings_seen INTEGER NOT NULL DEFAULT 0,
    queued        INTEGER NOT NULL DEFAULT 0,
    filtered      INTEGER NOT NULL DEFAULT 0,
    notes         TEXT
);

-- An append-only record of every state change, with who caused it.
CREATE TABLE state_log (
    id            INTEGER PRIMARY KEY,
    queue_entry_id INTEGER NOT NULL REFERENCES queue_entries(id) ON DELETE CASCADE,
    from_state    TEXT,
    to_state      TEXT NOT NULL,
    actor         TEXT NOT NULL,      -- 'human' | 'pipeline' | 'system'
    at            TEXT NOT NULL,
    note          TEXT
);

CREATE INDEX idx_state_log_entry ON state_log (queue_entry_id);

-- Constraint 1, enforced by the database itself.
--
-- Belt and braces alongside the application-level guard in queue/state.py: even a stray UPDATE
-- from a REPL cannot move an entry to 'submitted' unless a human action logged itself first.
-- The application layer writes the state_log row inside the same transaction, immediately
-- before the UPDATE.
CREATE TRIGGER trg_submitted_requires_human
BEFORE UPDATE OF state ON queue_entries
FOR EACH ROW
WHEN NEW.state = 'submitted' AND OLD.state <> 'submitted'
BEGIN
    SELECT RAISE(ABORT, 'constraint 1: submitted requires a logged human action')
    WHERE NOT EXISTS (
        SELECT 1 FROM state_log
        WHERE queue_entry_id = NEW.id
          AND to_state = 'submitted'
          AND actor = 'human'
    );
END;

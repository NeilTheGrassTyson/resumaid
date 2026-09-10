# 0002. Local-first stack: Python + SQLite + FastAPI + React SPA

Status: accepted     Date: 2026-08-31

## Context

`CLAUDE.md` settles that this runs locally, for one user at a time, with no hosting target, and
explicitly forbids assuming a stack before the founder approves one. It also warns that being
profile-agnostic "is about *whose* search the tool can serve, not about how it is deployed" —
generality is not a licence for multi-tenancy.

The MVP has to: fetch and normalize JSON from several job APIs; extract text from PDF and DOCX
resumes; score postings and explain the scores; persist a queue and an application history; and
present a triage UI good enough that a person opens it every morning.

Three options were put to the founder.

## Decision

Python 3.11+ core managed by `uv`, SQLite via stdlib `sqlite3` with explicit SQL and numbered
migrations, Pydantic domain models, `typer` CLI, FastAPI local API, and a React + TypeScript +
Vite SPA for the review queue.

Three rules hold the SPA's cost down:

1. `resumaid serve` is one process — FastAPI mounts the built SPA at `/`. Vite's dev server is
   for UI work only.
2. The API contract is one generated file: `openapi-typescript` emits `ui/src/api/types.ts` from
   FastAPI's schema. No hand-maintained duplicate types.
3. Every mutating route has a `typer` twin calling the same service function, so the pipeline is
   scriptable and testable without a browser — and the UI is never the only path to a state
   transition.

Bind to `127.0.0.1`. No auth, no accounts, no tenancy.

## Alternatives considered

- **Python + FastAPI + server-rendered Jinja/HTMX.** Recommended by Claude: one toolchain, no
  build step, no `node_modules`. The founder chose the SPA for triage ergonomics — a
  keyboard-driven, three-pane view that is read daily is where a component framework earns its
  overhead. Rejected on UX, not on cost, and the three rules above recover most of what it
  offered.
- **TypeScript end to end (Bun/Node + SvelteKit).** One language across fetching and UI, good
  JSON ergonomics. Rejected because PDF/DOCX-to-text extraction is materially weaker in JS, and
  resume ingestion is a load-bearing MVP feature, not a corner.
- **Postgres + Redis + a worker queue, in Docker Compose.** Rejected outright: a multi-tenant
  shape with no single-user payoff, and ops burden on a machine that is meant to run one command.
- **Electron desktop app.** Packaging cost for something a localhost tab already does.
- **An ORM (SQLAlchemy).** The schema is a dozen tables and the queries — ranking, diversity
  capping, duplicate detection — are the interesting part. Explicit SQL keeps them readable.

## Consequences

Two toolchains and a build step, accepted deliberately. CI must check that the generated API
types are not stale, or the SPA and API drift. In exchange: the triage UI can be genuinely fast,
and Python keeps document parsing, text processing, and the LLM SDK on their strongest ground.

SQLite means no concurrent writers, which is correct for one user and would need revisiting if
hosting ever happened — an open question `CLAUDE.md` leaves closed for now.

## Revisit when

Hosting stops being hypothetical, or the SPA's maintenance cost visibly exceeds what its
ergonomics buy.

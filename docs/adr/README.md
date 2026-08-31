# Architecture decision records

Implementation decisions, each with the alternatives it beat and why.

These sit **beneath** `CLAUDE.md`, never beside it. The constitution holds the non-negotiable
constraints; an ADR records a decision made *within* them. An ADR may explain how a constraint is
enforced — it may never trade one away.

An accepted ADR is immutable. Changing course means a new ADR that supersedes the old one; the
old file stays, marked superseded.

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-record-architecture-decisions-in-adrs.md) | Record architecture decisions in ADRs | accepted | 2026-08-31 |
| [0002](0002-local-first-stack.md) | Local-first stack: Python + SQLite + FastAPI + React SPA | accepted | 2026-08-31 |
| [0003](0003-queue-state-machine-no-auto-submit.md) | Queue state machine and the no-auto-submit invariant | accepted | 2026-08-31 |
| [0004](0004-ranking-gate-then-multiplicative-decay.md) | Ranking: a hard gate, then multiplicative recency and confidence | accepted | 2026-08-31 |
| [0005](0005-resume-selection-union-profile-plus-emphasis.md) | Resume selection: union profile for matching, per-document emphasis for selection | accepted | 2026-08-31 |
| [0006](0006-hybrid-llm-adjudication-near-the-floor.md) | Hybrid LLM use: deterministic gate, adjudication near the floor only | accepted | 2026-08-31 |
| [0007](0007-source-set-and-self-feeding-board-registry.md) | Source set, and a self-feeding ATS board registry | accepted | 2026-08-31 |
| [0008](0008-applications-log-and-oa-prediction.md) | Applications log as a durable table; OA predicted from runtime data | accepted | 2026-08-31 |
| [0009](0009-link-only-entries-and-paste-to-upgrade.md) | Link-only entries and paste-to-upgrade | accepted | 2026-08-31 |

## Format

```
# NNNN. Title
Status: proposed | accepted | superseded by NNNN     Date: YYYY-MM-DD
## Context      — the forces that made a choice necessary
## Decision     — what we do, present tense
## Alternatives considered — each option, and the specific reason it lost
## Consequences — what this buys, what it costs, what it makes harder
## Revisit when — the observation that should reopen this
```

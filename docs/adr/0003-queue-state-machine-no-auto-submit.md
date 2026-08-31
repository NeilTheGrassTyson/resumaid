# 0003. Queue state machine, and the no-auto-submit invariant

Status: accepted     Date: 2026-08-31

## Context

Constraint 1 is the load-bearing design decision in this project: the tool prepares
applications; a human clicks send. `CLAUDE.md` notes this is not only a legal hedge —
auto-fired applications get flagged as spam by ATS systems, which lowers response rates, so the
human-in-the-loop is also the thing that makes the tool work.

A constraint stated only in prose degrades. Someone adds a convenience path, a flag, a "just for
testing" branch, and the property is gone with nothing failing. The question is how to make it a
property of the code.

## Decision

A queue state machine whose transition table is data in one place
(`src/resumaid/queue/state.py`), with three layers of enforcement.

**1. The state machine.** `approved` and `submitted` are distinct states.
`approved` means "the human said yes, prepare this for me" — it resolves the resume path and
opens the posting. It triggers no network call to any employer. `submitted` is a fact the human
reports after applying. There is no transition from any pipeline state directly to `submitted`.

**2. The actor check.** Every transition takes an `actor` (`human`, `pipeline`, `system`). A
`HUMAN_ONLY` set names the transitions only a human may cause; `submitted` is unreachable for
any other actor. Violations raise `UnauthorizedActor` rather than returning a boolean, so a
caller cannot ignore the result.

**3. A database trigger.** `trg_submitted_requires_human` refuses any UPDATE to
`state = 'submitted'` unless a `state_log` row for that entry records a `human` actor. The
application layer writes that row inside the same transaction, immediately before the UPDATE.
This holds even against a stray statement typed into a REPL.

Three tests enforce the property end to end: a full pipeline run produces zero `submitted`
transitions; the pipeline makes no outbound request outside the permitted-source allowlist; and
the transition rejects a non-human actor.

## Alternatives considered

- **A boolean `submitted` column any code path may set.** The obvious shape, and exactly the one
  that decays. Nothing distinguishes a human's write from a background job's. Rejected.
- **Conflating `approved` with `submitted`.** Simpler UI, one fewer state. Rejected because it
  destroys the distinction constraint 1 exists to draw, and the reconciliation prompt
  (REVIEW_QUEUE_SPEC.md §6.4) would have nothing to reconcile — you could never tell what you
  approved but never sent.
- **Application-layer checks only, no trigger.** Sufficient in principle; the trigger costs
  almost nothing and covers the case where someone bypasses the service layer. For the one
  constraint the project describes as non-negotiable, redundancy is warranted.
- **Trigger only, no application check.** Worse errors, later, with no useful message.

## Consequences

The `submitted` path is deliberately awkward to reach from code: it takes an explicit human
actor and writes a log row first. That awkwardness is the point, and future work should not
smooth it away.

The `state_log` table grows without bound. It is small, and it is the audit trail for what the
tool did and who caused it — worth the space.

`filtered` entries are retained rather than deleted, so the gate's rejections stay auditable.

## Revisit when

Never, for the invariant itself. The transition table will grow as states are added; adding a
state means deciding explicitly which actors may reach it.

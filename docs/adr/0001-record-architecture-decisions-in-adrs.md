# 0001. Record architecture decisions in ADRs

Status: accepted     Date: 2026-08-31

## Context

`CLAUDE.md` is the constitution: five non-negotiable constraints, the build order, and the
questions the founder has settled or deliberately left open. It is deliberately short, and it
says so — "if this list grows past five items, it has stopped being a constitution and turned
into implementation detail."

That leaves a gap. Implementation decisions get made constantly — a ranking formula, a scoring
approach, a storage shape — and each is made against real alternatives. Recording only the winner
leaves a future reader unable to tell a considered choice from an accident, and unable to know
whether a change they are contemplating was already tried and rejected.

## Decision

Every architecturally significant decision gets a numbered file in `docs/adr/`,
`NNNN-kebab-title.md`, listed in `docs/adr/README.md`. The format is MADR-lite:

- **Context** — the forces that made a choice necessary.
- **Decision** — what we do, present tense.
- **Alternatives considered** — each option and the specific reason it lost.
- **Consequences** — what this buys, what it costs, what it makes harder.
- **Revisit when** — the observation that should reopen it.

Two rules:

1. **An ADR is immutable once accepted.** Changing course means a new ADR that supersedes the
   old one; the old file stays, marked superseded. The value is the trail.
2. **ADRs sit beneath `CLAUDE.md`, never beside it.** The constitution holds the
   non-negotiables; an ADR records a decision made *within* them. An ADR may explain how a
   constraint is enforced. It may never trade one away.

"Alternatives considered" is the load-bearing section. An ADR without a real rejected option is
usually documenting a non-decision.

## Alternatives considered

- **Nothing; rely on code comments and commit messages.** Comments explain what code does, not
  what else was on the table. Commit messages are searchable only if you already know what to
  search for. Rejected.
- **A single growing DESIGN.md.** Cheaper to start, but it invites editing history away: the
  reason a decision was made gets overwritten by the reason the next one was. Rejected for the
  same reason ADRs are immutable.
- **Extend `CLAUDE.md` with these decisions.** Directly against its own stated design. It would
  turn the constitution into a reference doc and bury the five constraints. Rejected.

## Consequences

A small per-decision writing cost, paid at the moment the decision is made — when the reasoning
is available rather than reconstructed. In exchange, the rationale survives. ADRs are written in
the same commit as the code they describe; one written weeks later is a reconstruction, not a
record.

## Revisit when

The folder grows large enough that finding the relevant ADR is hard. That is a table-of-contents
problem, not a reason to stop.

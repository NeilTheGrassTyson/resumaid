# 0004. Ranking: a hard gate, then multiplicative recency and confidence

Status: accepted     Date: 2026-08-31

## Context

`CLAUDE.md` sets three rules for every search: fit filters must *remove* low-fit roles rather
than rank them low (constraint 5); recency counts, because applications land better before a
posting has collected hundreds of responses; and breadth counts, so the queue should not be the
same handful of companies every day.

These pull against each other. A single blended score satisfies none of them cleanly, and the
throughput setting (roughly 5 submissions/day) creates pressure to pad a thin day with weak
roles — the exact failure the tool exists to avoid.

## Decision

Ranking is two stages, and the gate is upstream of everything.

**Stage 1 — the gate.** Hard filters, then the already-applied check, then a fit floor with an
optional per-family bar. Failures land in `filtered` with the reason recorded, retained for
audit rather than deleted. The floor never moves to fill a quota.

**Stage 2 — the rank**, among survivors only:

```
rank_score     = fit_score × recency_factor × confidence_factor
recency_factor = floor + (1 - floor) * exp(-age_days / τ)     floor = 0.75, τ = 21 days
confidence     = high 1.00 | medium 0.92 | low 0.85
```

Then a diversity pass caps any one company at 2 entries per slate and round-robins across
companies, and the slate is sized at `ceil(submissions_per_day × surface_multiplier)` — a
**ceiling on what is shown**, never a quota to be filled.

Two properties of the curve are deliberate, and both are asserted in tests:

- **It decays toward the floor rather than being clipped at it.** The first draft used
  `clamp(exp(-age/14), 0.60, 1.0)`, which reaches its floor at ~4 days and thereafter cannot
  distinguish a one-week-old posting from a three-month-old one. The asymptotic form keeps
  separating them (3d → 0.97, 30d → 0.81, 60d → 0.76).
- **The floor bounds what recency can do.** Since the factor never drops below 0.75, recency can
  overcome a fit gap of at most 1/0.75 ≈ 33%. An 85-fit role two months old still outranks a
  fresh 62.

## Alternatives considered

- **One blended weighted sum of fit and recency** (`0.7·fit + 0.3·recency`). The obvious design.
  Rejected: an additive recency term can promote an arbitrarily weak role above an arbitrarily
  strong one given enough age difference. That inversion is what constraint 5 names.
- **An additive recency bonus on top of fit.** The same defect, less visibly.
- **A clipped exponential with a hard floor** (`clamp(exp(-age/τ), floor, 1)`). This was the
  first draft and it was wrong in practice: with τ=14 and floor=0.60 it saturates within days,
  so recency stops working almost immediately while *also* permitting a 1.67× inversion.
  Both problems, no compensating benefit.
- **Claiming recency can never invert fit order.** Considered and rejected as false. No
  multiplier below 1.0 prevents every inversion — if it did, recency would have no effect at
  all. The honest design states the gap it permits (33%) and tests it, rather than asserting a
  guarantee the arithmetic does not support.
- **Sorting by recency and breaking ties on fit.** Rejected: makes freshness dominant, which
  directly contradicts "quality over volume".
- **No diversity cap.** Rejected: one company with a large careers page would fill the slate,
  against "breadth counts".
- **Letting the floor drop when the queue is thin.** Rejected explicitly. `CLAUDE.md`: "If only
  three roles clear it on a given day, three get queued." The surface multiplier tunes how many
  of the roles that already cleared the bar are shown — it never touches the bar.

## Consequences

Ranking is inspectable: every entry carries its dimension subscores, the evidence behind each,
and the recency note. A surprising position in the queue can always be traced to a reason.

τ and the floor are tunables, and changing the floor changes the invertible-gap bound — so the
test asserting the bound must be updated deliberately, which is the point.

A thin day produces a thin queue. That is correct behavior, and the UI should say so rather
than looking broken.

## Revisit when

The benchmark run in `BENCHMARK_PROFILE.md` shows stale roles crowding out fresh ones or the
reverse, or the observed approval rate suggests the floor itself is miscalibrated.

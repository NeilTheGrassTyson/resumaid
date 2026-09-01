# 0010. Offline place resolution, and weighted location preferences

Status: accepted     Date: 2026-09-01

## Context

`CLAUDE.md` names location a first-class matcher input, "not a post-hoc filter on a generic
result set". The first implementation did not really honor that. It was effectively binary: an
exact metro-name match scored 100, and everything else got a flat score determined only by
relocation willingness. Two consequences:

- **No notion of near.** A role 20 minutes away in the next state scored identically to one
  2,000 miles away, because matching was string equality on metro names. For anyone living near
  a state line — a large share of US metros — that is badly wrong.
- **No notion of preference strength.** Every declared metro was equally wanted. There was no
  way to say "Boston ideally, Denver at a push", which is how people actually think about where
  they'd move.

`Profile.locations` existed on the model but was never populated, so the tool did not even know
where the user lived.

Measuring distance means knowing where places are, and that is the decision this ADR records.

## Decision

**A bundled place table.** `src/resumaid/data/us_places.csv` holds the 1,000 most populous US
places with state, latitude, longitude and population — about 37KB. `geo.py` resolves a
free-text location string to a place and computes great-circle distance in miles.

Population and coordinates originate with the US Census Bureau, a US government work in the
public domain, assembled via the MIT-licensed `plotly/datasets` repository. It is factual data:
city, state, population, coordinates.

**Home location** comes from the resume's contact block (`detect_home_location`, first eight
lines only — a city further down belongs to an employer or a school), overridable with
`locations.home` in `interests.yaml`.

**Weighted preferences.** `locations.places` takes entries of `{place, weight}` or
`{state, weight}`, using the same numeric weight `RoleFamily` already uses, so "how much do I
want this" means one thing across the whole config. The legacy `metros` list keeps working,
treated as places at full weight.

**Scoring is best-of** across three signals: a place you named (100 × weight), a state you named
(88 × weight), and proximity to home (100 at the door, decaying to 82 at the edge of your
radius, then decaying further toward a ceiling set by your relocation willingness). Every
outcome names the actual distance, so "271mi from Boston, MA" is what the queue shows.

**The gate filters on distance only when it is sure.** Beyond `max_distance_miles` with
`relocation: "no"` and no explicit naming of the place is a hard fail, per constraint 5. But a
place the table cannot resolve is *not* filtered — see Consequences.

## Alternatives considered

- **A geocoding API** (Nominatim, Google, Mapbox). The obvious way to get coordinates, and
  wrong here twice over: this tool must work with no network (ADR 0002), and it would send the
  user's home city and every posting location to a third party on every run, which is exactly
  the leakage constraint 4 exists to prevent. Rejected on both counts, not on cost.
- **State and metro tiers with no distance at all.** No dataset, no math, and it would have
  covered "other states or cities of more interest" completely. Rejected because it cannot
  express "within commuting distance": a role 20 minutes over a state line would still read as
  another state, which is the specific failure that prompted this work.
- **The full ~30k-place gazetteer** (~2MB). Handles small towns and exact suburb names. Rejected
  as disproportionate: postings name a metro or a state far more often than a small town, the
  file is 50× larger for coverage rarely exercised, and unresolved places already have a
  sensible fallback.
- **Named tiers (preferred / acceptable / last-resort)** instead of numeric weights. Easier to
  fill in without agonizing over 0.7 versus 0.8, and it reads better in the UI. Rejected to
  avoid a second vocabulary for preference strength alongside `role_families`' weights.
- **Position-inferred weights from an ordered list.** Least typing, but reordering would
  silently change scores and it cannot express "these three are equally good", which is common
  for metros.
- **Treating a low weight as a penalty.** Considered and deliberately not done: weights only
  raise a location's score. To rule somewhere out you leave it unnamed with `relocation: "no"`,
  or exclude the company. This matches how `RoleFamily.weight` behaves, and keeps "I'm mildly
  interested" from being confused with "keep this away from me".

## Consequences

Distance is real and explainable: the queue can say "41mi from Boston, MA, inside your 50mi
radius" rather than showing a number with no account of itself.

The table is a committed data file that will slowly go stale as populations shift. That is
acceptable — coordinates do not move, and population only affects which of several same-named
cities an unqualified string resolves to.

**Unresolvable locations are never filtered.** A military base, a small town, or an overseas
office is not in the table, and filtering on that would hide roles for a reason the user cannot
see or act on. Such entries pass the gate and are discounted by the scorer instead, so they land
low in the queue rather than vanishing. This is the same principle as link-only entries in
ADR 0009: partial information is surfaced honestly rather than treated as absence.

Coverage is US-only. A non-US search gets state-less fallback behavior — correct but coarse.

## Revisit when

The search goes outside the US, postings routinely name places the table lacks, or the user
wants a location ruled out rather than merely ranked below others.

# 0007. Source set, and a self-feeding ATS board registry

Status: accepted     Date: 2026-08-31

## Context

Constraint 3 permits public ATS JSON APIs, licensed aggregator APIs, and Sonar for company
research — and requires that a source whose status is unclear be treated as disallowed until
checked. `CLAUDE.md` settles Greenhouse, Lever, and Ashby first, plus one aggregator for
breadth, and leaves *which* aggregator open.

There is a practical problem underneath. The ATS APIs are per-company: each needs a board token,
and the tool has no way to know which companies exist. A hand-curated list means an empty queue
on day one and works against the "breadth counts" rule.

## Decision

**Sources:** Greenhouse (priority), Lever, Ashby, plus **both** Adzuna and USAJobs.

- Adzuna gives breadth — documented public API, free tier ≈1,000 calls/month, a creation date for
  recency scoring. It returns snippets, not full descriptions, so Adzuna-only entries arrive
  `partial` or `link_only`.
- USAJobs is the official US federal API: free, documented, unambiguously permitted, fully
  structured. Federal-civilian only, so it deepens one lane rather than adding breadth.

**Board discovery is self-feeding.** When an aggregator result's apply URL points at
`boards.greenhouse.io`, `jobs.lever.co`, or `jobs.ashbyhq.com`, the board token is extracted and
registered in `boards.yaml`. Later runs poll that company's ATS directly — permanently upgrading
a snippet into a full-description source at no extra API cost. `resumaid board add <url|token>`
covers companies the user names.

## Alternatives considered

- **One aggregator only.** Adzuna alone was the recommendation; the founder chose both. USAJobs
  is a small adapter and is the one source that is unambiguously permitted, which makes it cheap
  insurance as well as coverage.
- **JSearch or similar RapidAPI aggregators.** Rejected. Their indexes are substantially built
  from platforms whose terms prohibit scraping, which makes their status unclear at best —
  constraint 3 says treat that as disallowed until checked.
- **The undocumented Workday tenant JSON endpoint.** Rejected, and this is the important one.
  It is not a published public API, and each tenant carries the *employer's* terms rather than
  one central Workday policy, so "is this permitted" has a different answer per company.
  `CLAUDE.md` leaves this as an open Tier 1 question — deliberately deferred, **not** decided
  against on the merits. Until the founder decides, Workday roles enter as link-only records and
  nothing fetches that endpoint. This ADR does not close that question.
- **Scraping company careers pages directly.** Rejected under constraint 3 unless a specific
  site's robots.txt and terms permit it, which is a per-site check the MVP does not do.
- **Sonar for listing ingestion.** Explicitly excluded by `CLAUDE.md`; Sonar is for company
  research and fit-qualification.
- **Hand-curated `boards.yaml` only.** Predictable, but a cold start means an empty queue and it
  works against breadth. Kept as a supplement, not the mechanism.

## Consequences

Coverage compounds: every aggregator hit that resolves to a known ATS permanently improves the
tool's direct-source reach. Adzuna's free tier is the binding constraint on breadth, so queries
are batched and cached with conditional requests.

The Workday gap remains real and is now visible rather than assumed — `BENCHMARK_PROFILE.md`
says that is where this user's applications historically go, so the link-only path (ADR 0009)
carries more weight than it would otherwise.

## Revisit when

The founder decides the Workday question, Adzuna's free tier becomes binding, or the benchmark
run shows the board registry is not growing on its own.

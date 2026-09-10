# 0009. Link-only entries, and paste-to-upgrade

Status: accepted     Date: 2026-08-31

## Context

Not every posting can be pulled from a permitted source. Constraint 3 allows public ATS JSON
APIs and licensed aggregator APIs, and requires that a source whose status is unclear be treated
as disallowed until checked. That leaves real gaps:

- **Workday**, which `CLAUDE.md` records as an open Tier 1 question and which
  `BENCHMARK_PROFILE.md` names as one of the two places this user's applications have
  historically gone. The coverage gap is not hypothetical.
- Company careers pages whose robots.txt or terms have not been checked.
- Aggregator results that return a snippet rather than a description.

`CLAUDE.md` already settles the principle: "Link-only records are acceptable. When a posting
cannot be pulled from a permitted source, a record holding the company and a link to its careers
page or job posting is a valid queue entry. Partial coverage beats reaching for a source that
isn't permitted." What it does not settle is how such an entry behaves once it is in the queue —
how it is scored, ranked, and displayed without either misleading the user or being useless.

## Decision

Three levels of completeness, and an escape hatch.

`completeness` ∈ `full` | `partial` | `link_only`, mapping to `score_confidence`
`high` | `medium` | `low`, which feeds the `confidence_factor` in the rank (ADR 0004). A
link-only entry is therefore ranked, but discounted — present, and honestly labelled.

Four rules:

1. **Never fabricate.** A missing description is displayed as missing. The tool does not infer
   one from the title, summarize from the company, or borrow another posting's text.
2. **Visible provenance.** Every such entry carries a note naming where it came from and why the
   description is absent, plus a badge in the UI. It never presents as a full record, and its
   score is shown with its confidence rather than as a bare number.
3. **Paste-to-upgrade.** The human opens the posting, copies the description, and pastes it in
   (`p`). The entry becomes `full`, is marked `human_paste`, and is re-scored at full
   confidence. This is the permitted manual path around a source the tool may not fetch, and it
   is deliberately one keystroke.
4. **No Stage 2 drafting from thin data.** The cover-letter drafter will refuse a `link_only`
   entry outright rather than produce a letter from a title and a company name.

An aggregator snippet is `partial`, not `full`. A two-line teaser is not a description, and
treating it as one would let the scorer draw confident conclusions from a fragment.

## Alternatives considered

- **Drop postings that cannot be fully retrieved.** Simplest, and it keeps every queue entry
  uniform. Rejected: it silently deletes the largest coverage lane this user actually applies
  through, and `CLAUDE.md` explicitly rules the other way. A queue that quietly omits Workday
  roles has not solved the user's problem, however clean its data model.
- **Fetch the missing description from the Workday tenant endpoint.** This is what would "fix"
  the gap, and it is out of bounds. The endpoint is undocumented, not a published public API,
  and each tenant carries the *employer's* terms rather than one central Workday policy — so
  permission has a different answer per company. Constraint 3 governs. It stays an open founder
  decision, not something resolved by an implementation ADR, and the host allowlist in
  `sources/base.py` enforces the exclusion in code.
- **Score link-only entries as though complete.** Rejected: it produces false precision. A score
  built on a title and a company name is not comparable to one built on a full posting, and
  presenting them on the same scale teaches the user to distrust every score.
- **Rank link-only entries last, unconditionally.** Rejected as too blunt. A strongly-titled role
  at a target company is worth seeing even without its description; the confidence discount
  expresses "trust this less" without burying it.
- **Have an LLM guess the description from the title and company.** Rejected outright. It is
  invention, which is the one thing this project's document handling must never do.
- **Make paste-to-upgrade a form with fields.** Rejected: friction kills it. If upgrading an
  entry is a chore, nobody does it, and the Workday lane stays permanently second-class.

## Consequences

Coverage extends into sources the tool cannot read, at the cost of a queue whose entries are not
uniform — the UI has to carry the distinction visibly, and the ranking has to account for it.

Paste-to-upgrade puts a small amount of manual work on the user, which is the honest trade for
staying inside constraint 3. It also produces the best-quality entry in the system, since a
human-pasted description is complete by construction.

If the Workday question is ever resolved in favor of some permitted path, link-only stops being
the primary mechanism for that lane and reverts to what it is here: a fallback for genuinely
unreachable postings.

## Revisit when

The founder decides the Workday question, or a licensed aggregator turns out to index
Workday-posted roles with full descriptions.

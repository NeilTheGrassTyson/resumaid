# 0006. Hybrid LLM use: deterministic gate, adjudication near the floor only

Status: accepted     Date: 2026-08-31

## Context

Matching needs judgment. Titles are synonymous in ways keywords miss ("Member of Technical
Staff", "Software Engineer I", "New Grad SWE"), and skill lists overlap semantically rather than
lexically. An LLM is good at exactly this.

It also cuts against two constraints. Constraint 4 says data stays local or encrypted, and
nothing leaves the machine beyond the API calls strictly required. Constraint 5 needs the fit
bar to be a deliberate, inspectable threshold — and scores produced wholesale by a model are
hard to debug and harder to tune. Cost and latency scale with every posting scored.

## Decision

Deterministic scoring and gating; the LLM adjudicates only near the bar.

- Hard filters and dimension scores are computed deterministically — lexical overlap plus local
  embeddings for title and skill synonymy — and each subscore carries the evidence string that
  produced it.
- Only entries whose score lands within a band around the fit floor get an LLM call, returning a
  verdict plus one sentence of reasoning. Near-the-bar cases are where judgment actually changes
  an outcome.
- Resume parsing is deterministic first; an LLM pass handles only sections the deterministic
  parse could not segment, and every field it returns carries a pointer to its source span.
- What leaves the machine on an adjudication call is the posting text plus a skills/education
  summary. Never a resume file, never contact details. `match/llm.py` asserts on the payload
  before sending.

## Alternatives considered

- **Deterministic only, no LLM until Stage 2.** Maximum privacy, zero cost, and nothing leaves
  the machine during discover/score/queue. Rejected because pure lexical matching handles title
  and skill synonymy badly, and the resulting false negatives are invisible — a role that never
  surfaces cannot be corrected by the human in the loop. This is the strongest rejected option
  and would be the right fallback if API access disappeared.
- **LLM scores every posting.** Best raw quality and the richest explanations. Rejected on three
  counts: cost and latency scale with volume; scores become hard to debug or tune, which
  undermines constraint 5's requirement that the bar be a decision; and it sends far more data
  off-machine than constraint 4 contemplates.
- **A local model for everything.** Attractive for constraint 4, rejected for the MVP as a large
  dependency and quality risk. Local embeddings are used; local generation is not, yet.

## Consequences

Scores stay explainable and cheap, and the LLM is confined to the cases where it changes an
outcome. The band's width is a tunable that trades cost against quality. There is a seam here:
if the deterministic scorer is badly calibrated, the band lands in the wrong place and
adjudication is spent on the wrong entries — so the benchmark run in `BENCHMARK_PROFILE.md` is
the check that matters.

Scoring must work with the LLM disabled: no API key configured means near-the-bar entries fall
back to their deterministic score and are flagged, rather than failing the run.

## Revisit when

A local model becomes good and cheap enough to run adjudication offline, or the benchmark shows
the band is consistently missing the cases that need judgment.

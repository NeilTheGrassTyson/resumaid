# 0005. Resume selection: union profile for matching, per-document emphasis for selection

Status: accepted     Date: 2026-08-31

## Context

`CLAUDE.md` is explicit that resumes in the MVP are handled by **selection, not tailoring**: the
user uploads the resumes they already maintain, and the tool names the best-fitting one on each
queue entry. Per-role tailoring is the Later phase, and the build order says not to design
around it.

`BENCHMARK_PROFILE.md` describes the real shape: one master resume plus three hand-tailored
one-pagers (AI development, software engineering, defense/aerospace). The master is a superset,
roughly 70% longer than any variant.

Two questions follow. What does the matcher score a posting *against* when the user has four
documents? And how is the recommended document chosen?

## Decision

They are different questions and get different answers.

**Matching scores against the union profile.** "Am I a fit for this role?" is a fact about the
person, not about which PDF they happen to send. Skills, education, and seniority are merged
across all uploaded documents into one `Profile`, which is what the scorer sees.

**Selection uses per-document emphasis.** "Which of my documents argues this best?" is answered
from each document's *emphasis* — its top terms, weighted toward the first third of the page,
since a resume puts what it wants read first at the top.

The metric is **concentration, not overlap count**: the share of a document's emphasis terms
that appear in the posting. This distinction is load-bearing. A raw count rewards breadth, and
the master resume — a superset roughly 70% longer than any variant — matches more of everything
by construction, so counting hands it every role and the three tailored one-pagers never get
picked. Asking what *share* of a document is about this posting inverts that correctly: the
master's emphasis is diluted across every topic the user has ever worked on, while the defense
one-pager is concentrated.

A master resume additionally carries a 0.85 penalty, so it remains the fallback rather than the
pick even on a tie. The runner-up is offered as a one-key switch.

The tool selects among documents the user wrote. It does not rewrite, merge, reorder, or
generate one, and nothing here is scaffolding for the code that eventually will.

## Alternatives considered

- **Score every resume separately against every posting, take the best.** The obvious approach.
  Rejected on two counts. It costs N× the scoring work for a question that does not need it —
  and, more importantly, it conflates fit with document choice. A role the user is genuinely
  qualified for should not score lower because the wrong PDF was tried against it; a fit score
  that moves depending on which document was sampled is not a fit score.
- **Pick by filename convention** (`resume_defense.pdf` for defense roles). Rejected: it
  requires the user to adopt a naming scheme, hardcodes role families into a convention, and
  breaks silently on rename. Emphasis is derived from what the document actually says.
- **Ask an LLM to pick.** Rejected as disproportionate: term overlap answers this well, and it
  would send resume text off-machine for a low-stakes choice (constraint 4).
- **Generate a tailored resume per role now.** Explicitly the Later phase. Declined on scope,
  not on merit — `BENCHMARK_PROFILE.md` records the worked example for when it is built, and
  `RESUME_STRATEGY.md` will hold the rules.
- **Embedding similarity between document and posting.** A reasonable future upgrade. Rejected
  for the MVP because the resulting choice would be much harder to explain, and the queue entry
  has to say *why* a document was picked.

## Consequences

Selection quality depends on the user's documents actually being differentiated. If someone
uploads four near-identical resumes, the recommendation is close to arbitrary — which is
honest, and the rationale string makes it visible rather than implying a judgment that was not
made.

Emphasis is recomputed when a document is re-added, so editing a resume updates its emphasis
without any separate step.

## Revisit when

Per-role tailoring is built, at which point selection becomes the fallback for when tailoring is
declined rather than the primary mechanism.

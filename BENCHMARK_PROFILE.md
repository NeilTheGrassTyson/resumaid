# Benchmark profile

A real job search, recorded here as the reference case for evaluating the matcher and
the resume tailoring.

**This file is test data, not configuration.** Nothing in it is a default, and the
tool must not read it as one. Per CLAUDE.md, the tool is profile-agnostic — targeting
comes from an uploaded resume plus declared interests at runtime. This profile exists
so there is something concrete to measure changes against.

No resume files or personal contact details are committed to this repository. What
follows describes structure and behavior only, per constraint 4.

---

## The search

**Resume:** the founder's own, supplied at runtime like any other.

**Role families, in priority order:**

1. **Aerospace and defense** — software engineering, or internal AI work. The strongest
   interest, with AI-focused defense startups as the sharpest version of it. Anduril is
   the gold-standard example of the kind of company meant.
2. **Big tech and general software.**
3. **Finance** — lowest priority. Little business background to draw on, so these roles
   need a higher bar to be worth preparing.

**Filters:** degree level, education, industry interest.

**Throughput:** 5 applications **submitted** per day. The queue therefore has to hold
more than 5 — enough that five survive review — without lowering the fit bar to fill
the number.

**Where these applications have historically gone:** mostly Workday and Greenhouse.
This is the concrete reason the Workday coverage gap in CLAUDE.md's Open questions
matters rather than being hypothetical — a matcher that scores well here while
surfacing nothing from the user's primary channel has not actually solved the problem.

---

## Resume tailoring: the reference pattern

The founder maintains one master resume plus three hand-tailored one-pagers (AI
development, software engineering, defense/aerospace), currently produced by prompting
an AI to pull from the master. Those four documents are the worked example of what the
tool should automate — with one change: **the target is a specific posting, not an
industry.** The three industry one-pagers are a workaround for having to tailor by
hand. Given a per-role function, they stop being necessary.

What the master holds and the variants don't: the master is a superset, roughly 70%
longer than any variant, including early-career roles and every bullet ever written.
Each variant is a one-page cut of it.

### What never changes

Identity and contact block. Education block — school, degree, expected graduation,
minor, GPA, honors, study abroad, organizations — appears identically in all four.
Employers, job titles, and employment dates are never reworded. Metrics stay exactly
as written: a bullet claiming a ~80% reduction says ~80% in every variant it appears in.

### What the tailoring actually does

Six operations, all observed across the real documents:

1. **Drops whole blocks.** Two pre-college roles sit in the master and appear in none
   of the variants. Relevance, not recency, decides.
2. **Selects bullets.** The current internship carries thirteen bullets in the master
   and six in each variant — a *different* six each time.
3. **Merges.** Two adjacent master bullets (a controller framework; the serial
   instrument orchestration built on it) collapse into one sentence in the software and
   defense variants, where they're supporting detail. The AI variant keeps its
   ML-accelerator work split across two bullets, because there it's the point.
4. **Reorders by relevance.** The neuromorphic-accelerator benchmarking bullet is
   second in the AI variant, fifth in the software one, and absent from defense — which
   instead keeps a technical-documentation bullet the other two drop.
5. **Swaps projects.** An OSINT aggregation pipeline appears only in the defense
   variant; an Android productivity app appears in the other two and not in defense.
6. **Regroups the skills line.** Same underlying skill set, reordered and reclustered:
   defense leads with serial protocols, register-level SCPI, and motion control; AI
   leads with the ML SDK, model families, containerization, and agent tooling; software
   leads with general frameworks and tooling.

One conditional field is worth noting: a citizenship line is absent from the master and
present in all three tailored variants — a detail that is material to some employers
and noise to others. Per-role tailoring should decide this from the posting, not from a
fixed template.

### The line the LLM may not cross

Rewording is allowed for **framing**, never for **claims**. Changing a lead verb to
match what the posting emphasizes is fine — the same work legitimately reads as
"evaluated" to one reader and "prototyped" to another. Changing seniority, ownership,
scope, or a number is not. Every line in a variant must trace to a line in the master;
if it can't, it was invented, and per CLAUDE.md that is the one thing tailoring must
never do.

The one-page limit is a hard budget, which makes this a constrained selection problem
rather than summarization: the question is never "how do I shorten this," it's "which
six of these thirteen earn the space, for this posting."

---

## How to use it

**Matching.** Run against this profile and read the surfaced roles as a person would:
does an aerospace-defense AI role outrank a generic finance one? Does a posting from
this week outrank an equally-fitting one from two months ago? Are the companies varied,
or the same handful every run?

**Tailoring.** Feed the master plus a real posting and compare the output against the
hand-tailored variant for that family. Close is good; identical is not the bar. What
matters is whether the selection is defensible — did it keep the six bullets a person
would have kept, and did every line come from the master?

A change that makes either result worse is suspect, even if it looks better in the
abstract.

## What it does not prove

This is one person's search, in a narrow set of industries, early in their career, with
a technical resume. Passing it says the matcher and the tailoring work here — not that
they generalize. A second profile with a different shape — different field, different
seniority, a career change, a non-technical resume — would be worth adding before
trusting either broadly.

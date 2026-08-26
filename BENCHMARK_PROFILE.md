# Benchmark profile

A real job search, recorded here as the reference case for evaluating the matcher.

**This file is test data, not configuration.** Nothing in it is a default, and the
tool must not read it as one. Per CLAUDE.md, the tool is profile-agnostic — targeting
comes from an uploaded resume plus declared interests at runtime. This profile exists
so there is something concrete to measure scoring changes against.

---

## The search

**Resume:** the founder's own, supplied at runtime like any other. Not committed here.

**Role families, in priority order:**

1. **Aerospace and defense** — software engineering, or internal AI work. The strongest
   interest, with AI-focused defense startups as the sharpest version of it. Anduril is
   the gold-standard example of the kind of company meant.
2. **Big tech and general software.**
3. **Finance** — lowest priority. Little business background to draw on, so these roles
   need a higher bar to be worth preparing.

**Filters:** degree level, education, industry interest.

**Throughput:** roughly 5 applications per day reaching the review queue.

**Where these applications have historically gone:** mostly Workday and Greenhouse.
This is the concrete reason the Workday coverage gap in CLAUDE.md's Open questions
matters rather than being hypothetical — a matcher that scores well here while
surfacing nothing from the user's primary channel has not actually solved the problem.

---

## How to use it

Run the matcher against this profile and read the surfaced roles as a person would:
does an aerospace-defense AI role outrank a generic finance one? Does a posting from
this week outrank an equally-fitting one from two months ago? Are the companies varied,
or is it the same handful every run?

A scoring change that makes these results worse is suspect, even if it looks better in
the abstract.

## What it does not prove

This is one person's search, in a narrow set of industries, at one point in their
career. Passing it says the matcher works here — not that it generalizes. A second
benchmark profile with a different shape (different field, different seniority, a
career change) would be worth adding before trusting the scoring broadly.

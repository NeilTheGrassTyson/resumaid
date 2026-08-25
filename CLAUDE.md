# Project overview

A personal job-search copilot. It does three things.

**Discover.** It pulls open roles from legitimate, permitted sources — public ATS
JSON APIs, licensed aggregator APIs, and targeted company research. It does not
scrape platforms that prohibit scraping.

**Match and tailor.** It scores each opening against a small set of base resumes
(3–6), then generates a tailored resume variant and a cover-letter draft for the
roles that actually fit.

**Queue, never auto-fire.** Every prepared application lands in a review queue. A
human reads it, approves it, and submits it. The tool never submits on its own.

The third one is the load-bearing design decision in this repository. Nearly every
architectural question that comes up later — what the queue looks like, what gets
stored, which integrations are worth building — resolves against it. See the
constraints below before proposing anything that touches the submit step.

This is a solo personal tool first and a possible public product later, in that
order. Prefer the design that is right for one user running it on their own
machine; do not pre-build for a multi-tenant product that may never exist.

---

## Non-negotiable constraints

These are the principles that don't get traded away for speed. They are meant to
be stable — if this list grows past five items, it has stopped being a constitution
and turned into implementation detail, which belongs in a reference doc instead.

**1. No unattended submission.** The tool prepares applications; a human clicks
send. This is not only a legal hedge. Auto-fired applications at scale get flagged
as spam by ATS systems and job platforms, which lowers response rates — so the
human-in-the-loop is also the thing that makes the tool work.

**2. No ToS-violating automation.** No headless-browser session automation against
platforms whose terms prohibit bots or scraping — LinkedIn, Indeed, Glassdoor, and
anything else in that category. No CAPTCHA solving, no bot-detection evasion, ever,
regardless of how the request is framed.

> Addressed to Claude specifically: if a task appears to require any of the above,
> **stop and say so.** Do not scaffold it. Do not leave a TODO for it. Do not build
> a "manual fallback" that is the same mechanism behind a flag. Say plainly that the
> approach is out of bounds here and propose the nearest permitted alternative.

**3. Legitimate data sourcing only.** Public ATS JSON APIs (Greenhouse, Lever,
Ashby, Workable, SmartRecruiters), licensed aggregator APIs (Adzuna, JSearch,
USAJobs, RemoteOK, Arbeitnow, and similar), and Perplexity's Sonar API for company
research and fit-qualification. No raw scraping of sites whose robots.txt or terms
disallow it. When a source's status is unclear, treat it as disallowed until checked.

**4. Data stays local or encrypted.** Resumes, cover letters, and any PII are stored
locally or encrypted at rest. Nothing leaves the machine beyond the API calls
strictly required for tailoring or lookup.

**5. Quality over volume.** A handful of well-crafted base resumes, tailored per
role, beats spray-and-pray. The matcher exists to surface a fit score and actively
filter out low-fit roles — not to maximize the number of applications sent.

---

## Two tiers of work

### Tier 1 — pause and think it through before building

- Anything that changes what happens at "submit" — including adding an ATS whose
  fields the tool can auto-fill.
- Storing any credential, cookie, or session token for a third-party site.
- Any new paid API or dependency.
- Any change to what data leaves the machine.

Tier 1 means stop and talk it through before writing code. At solo scale that is a
conversation, not a formal spec document — with one exception:
`REVIEW_QUEUE_SPEC.md` is worth writing as a real spec, because it is the safety
valve for constraint 1.

When it isn't obvious which tier something falls into, treat it as Tier 1.

### Tier 2 — just build it

- Matching and scoring logic changes.
- UI work and resume templates.
- Adding a new read-only data source that is clearly public and permitted — another
  ATS's public JSON API, for instance.
- Prompt changes to the tailoring and cover-letter generation.

---

## Stack — not yet chosen

Nothing has been decided. There is no approved backend, database, frontend, or
hosting target, and there is no code in this repository yet.

**Do not assume a stack and do not begin scaffolding one.** The first plan-mode
session proposes two or three options and the founder picks one; this section gets
filled in with the decision at that point.

---

## Situational references (not yet written)

These don't need to sit in context every session. Open them deliberately when the
work calls for it. None of them exist yet — create each one when the work that
needs it begins, rather than stubbing them out now.

- **RESUME_STRATEGY.md** — the 3–6 base resumes, what role family each is tuned
  for, and the tailoring rules: what an LLM is allowed to rewrite versus what it
  must leave alone. Never invent experience, employers, dates, or metrics.
- **DATA_SOURCES.md** — the running list of which ATS and aggregator APIs are wired
  up, their rate limits, and their auth requirements. Endpoint specifics live here,
  not in this file, so they can change without touching the constitution.
- **REVIEW_QUEUE_SPEC.md** — the UX of the human-approval step. The one piece worth
  treating as a real spec even at solo scale, per Tier 1 above.

---

## Open questions

Unresolved. Do not quietly answer these — they are the founder's to decide.

- Which 3–6 base resumes exist today, and what role family is each tuned for?
- Target scale: how many companies or roles per week is realistically reviewable
  alongside an actual job search?
- Local-only tool, or is a minimal hosted version worth standing up now?
- Which ATS and aggregator APIs to wire up first? This should be driven by where
  the target companies actually post. Many startups run Greenhouse, Ashby, or
  Lever; larger organizations often run Workday, whose public surface is
  considerably messier.

---

## Bootstrap — remove this section once the stack decision lands

One-time kickoff prompt. Paste it in plan mode, before any code is written. Once a
stack is approved and recorded above, delete this section — it is stale context
every session after that.

```
I'm building a personal job-search copilot for myself, possibly a product later.
Read CLAUDE.md — it's the constitution for this project, especially the "no
unattended submission" and "legitimate data sourcing only" constraints, which are
non-negotiable.

Before writing any code, research and propose 2–3 stack options, considering:

- This is a solo personal tool first. Don't default to the full multi-user-product
  stack (auth provider, hosted Postgres, separate frontend deploy) unless you can
  justify why a local-first tool (e.g. a Python CLI/service + SQLite + a simple
  local web UI) is worse for this use case.
- Data source integration order: start with 2–3 ATS public JSON APIs (Greenhouse,
  Lever, Ashby are good first targets — documented, no auth required) plus one
  aggregator API for broader coverage. Perplexity's Sonar API is for company
  research and fit-qualification, not for pulling structured listings — don't route
  the core ingestion through it.
- The review-queue UX (discover → score → tailor draft → human approves → human
  submits) is the central mechanic. Propose how that queue should work before
  touching the matching algorithm itself.
- Explicitly do NOT implement, scaffold, or leave TODOs for autonomous submission,
  headless-browser automation against LinkedIn/Indeed/Glassdoor, or any
  CAPTCHA/bot-detection bypass. If a stack option requires any of that to be
  useful, reject it and say so.

Stay in plan mode until I approve a direction.
```

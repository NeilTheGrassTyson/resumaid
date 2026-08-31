# Project overview

A personal job-search copilot. It does three things.

**Discover.** It pulls open roles from legitimate, permitted sources — public ATS
JSON APIs, licensed aggregator APIs, and targeted company research. It does not
scrape platforms that prohibit scraping.

**Match.** The user supplies their resumes and names the careers, industries, and
locations they're interested in. The tool parses the resumes into a structured profile,
scores each opening against it, and filters out the roles that don't fit.

**Draft.** For roles that clear the bar, the tool drafts a cover letter in the user's
own voice, learned from writing samples they supply. Per-role resume tailoring — cutting
a master resume down to a one-pager for a specific posting — is the end state, not the
starting point; see Build order below.

**Queue, never auto-fire.** Every prepared application lands in a review queue. A
human reads it, approves it, and submits it. The tool never submits on its own.

The third one is the load-bearing design decision in this repository. Nearly every
architectural question that comes up later — what the queue looks like, what gets
stored, which integrations are worth building — resolves against it. See the
constraints below before proposing anything that touches the submit step.

The tool is **profile-agnostic**. It holds no built-in idea of which roles are worth
having; it learns that at runtime, from a resume and a handful of declared interests.
No role family, employer, or industry is hardcoded anywhere in this repository.

That generality is about *whose* search the tool can serve, not about how it is
deployed. It still runs locally, for one user at a time. Prefer the design that is
right for one person running this on their own machine; being profile-agnostic is not
a reason to build multi-tenancy, accounts, or hosted storage.

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

## Build order

Three stages. Only the first is the MVP; the rest wait their turn.

### MVP — the job-application side

**Stage 1: discover, match, queue.** Pull openings from permitted sources, score them
against the profile and declared interests, and put what clears the bar into the review
queue. The user reads, approves, and submits. That is the whole loop minus the writing,
and it is the thing worth having working first.

Resumes in the MVP are handled by **selection, not tailoring**: the user uploads the
resumes they already maintain, and the tool names the best-fitting one on each queue
entry. Choosing among documents the user wrote is not the tailoring engine, needs none
of its machinery, and carries most of the day-one value.

**Stage 2: cover letters.** Draft a letter per queued role in the user's own voice,
learned from writing samples they supply.

The objective is **voice fidelity** — a letter that reads as something this person
wrote, which it substantially is: the experience is theirs and they approve every letter
before it goes anywhere. That is what to build for and evaluate against.

Not a build target: testing drafts against AI-detection services, or tuning output to
score below their thresholds. Two reasons, both practical. Those detectors are noisy,
disagree with each other, and change without notice, so anything fitted to them rots
immediately and silently. And the letter you get by chasing voice fidelity is the same
letter, arrived at in a way that stays true as the tools change. Build for voice.

Because the samples on hand are general writing rather than cover letters, the tool has
to separate this person's voice from the conventions of the genre — expect that to want
more sample text than voice-matching normally would. Evaluate on whether a letter sounds
like the user, not on whether it sounds unlike a machine.

### Later — resume review, then per-role tailoring

A review function over the user's existing resumes (what is weak, what a given posting
wants that isn't there), followed by the master-resume-to-one-pager tailoring described
in Matching and targeting. BENCHMARK_PROFILE.md holds the worked example.

This is last on purpose. It is the largest piece, it is worth building well rather than
quickly, and the queue is genuinely useful without it.

Nothing in this order touches the constraints. Stage 1 queues; it never submits.

---

## Matching and targeting

Targeting is input, not configuration baked into the repo. Every search starts the
same way:

1. **Resume in.** The user supplies one or more resumes. The tool parses them into a
   structured profile — skills, education and degree level, employers, dates, and the
   overall shape of the experience.
2. **Interests in.** The user declares what they're looking for: target careers or
   industries, and the locations they'll work in — remote, specific metros, or a
   willingness to relocate. Plus any hard filters that apply: degree level, seniority,
   clearance eligibility, and so on. Industry and location are first-class inputs to the
   matcher, not post-hoc filters on a generic result set.
3. **Matches out.** Openings are scored against the parsed profile and the declared
   interests together. Low-fit roles are filtered out, not merely ranked low.

Three rules apply to every search, whoever is running it:

- **Fit filters.** Per constraint 5, the matcher's job is to remove low-fit roles, not
  to maximize how many applications get prepared.
- **Recency counts.** A recently posted role ranks above an equally-fitting stale one.
  Applications land better before a posting has collected hundreds of responses.
- **Breadth counts.** Aim for a diverse, thorough set of companies rather than a short
  list of favorites re-checked every day.

Throughput is a user setting expressed as applications **submitted** per day, defaulting
to roughly 5. Because the human rejects some of what's queued, the pipeline has to
surface more than the target — start near 2–3x and tune it against the observed
approval rate.

The fit bar does not move to hit that number. If only three roles clear it on a given
day, three get queued; constraint 5 outranks the throughput setting, and a quota filled
with low-fit roles is the exact failure this tool exists to avoid.

One clarification, because the wording matters here more than anywhere else in this
file: the tool automatically **finds and prepares**. It never automatically **sends**.
Nothing in this section modifies constraint 1 — "auto" describes discovery and
tailoring, never submission.

If a proposed change would only make sense for one particular job search, it belongs
in a profile, not in the code. See BENCHMARK_PROFILE.md for the reference search used
to evaluate matcher quality — that file is test data, never defaults.

---

## Stack — local-first, specifics not yet chosen

Local-only is decided: this runs on one machine, for one user at a time, with no
hosting target. A hosted version is a possibility later, if the tool proves itself in
daily use — it is not something to design toward now, and it is not a reason to reach
for a multi-tenant architecture today.

The specific backend, storage, and UI are still open. **Do not assume a stack and do
not begin scaffolding one.** The first plan-mode session proposes two or three options
consistent with local-first, and the founder picks one; this section records the
decision at that point.

---

## Situational references

Open these deliberately when the work calls for it, rather than keeping them in context
every session.

- **BENCHMARK_PROFILE.md** — *exists.* A real job search used as the reference case for
  evaluating the matcher and the cover-letter drafter. Read it when working on scoring,
  ranking, filtering, or voice.
- **REVIEW_QUEUE_SPEC.md** — *not yet written, needed first.* The UX of the
  human-approval step: what a queue entry holds, how link-only entries behave, how
  recency and fit combine in the ordering. The one piece worth treating as a real spec
  even at solo scale, per Tier 1 above — and the MVP's central mechanic.
- **COVER_LETTER_VOICE.md** — *not yet written, MVP stage 2.* How writing samples become
  a voice model, and what the drafter may and may not do with the user's experience.
  Same rule as resume tailoring: nothing invented, every claim traceable.
- **RESUME_STRATEGY.md** — *not yet written, Later phase.* How a master resume becomes
  a tailored one-pager for a specific posting: what may be dropped, merged, reordered,
  or reworded, and what must survive untouched. Never invent experience, employers,
  dates, or metrics — every line in a variant must trace back to a line in the master.
  The rules belong here; any particular user's resumes do not. BENCHMARK_PROFILE.md has
  a worked example of the pattern.
- **DATA_SOURCES.md** — *not yet written.* Which ATS and aggregator APIs are wired up,
  their rate limits, and their auth requirements. Endpoint specifics live here, not in
  this file, so they can change without touching the constitution.

Create the unwritten ones when the work that needs them begins, rather than stubbing
them out now.

---

## Decided

- **Profile-agnostic, local, single-user** — see Project overview and Stack above.
- **Targeting is runtime input** — resume plus declared interests, per Matching and
  targeting above.
- **First sources** — Greenhouse, Lever, and Ashby public JSON APIs, plus one
  aggregator for breadth. Greenhouse is the priority: it is where a large share of
  roles actually post, and its job-board API is documented and public.
- **Build order** — MVP is the job-application side plus cover letters; resume review
  and per-role tailoring come after. See Build order above.
- **Link-only records are acceptable.** When a posting cannot be pulled from a
  permitted source, a record holding the company and a link to its careers page or job
  posting is a valid queue entry. Partial coverage beats reaching for a source that
  isn't permitted.

---

## Open questions

Unresolved. Do not quietly answer these — they are the founder's to decide.

**Workday sourcing — Tier 1, deliberately deferred.** Workday is a large share of where
applications actually get submitted, so this is the biggest coverage gap and it is not
a comfortable one to leave open. It stays open anyway, because Workday is the one
source constraint 3 cannot wave through. Workday career sites expose an undocumented
JSON endpoint that their own frontend calls; it is not a published public API, and each
tenant carries the *employer's* terms rather than one central Workday policy — so "is
this permitted" has a different answer per company. Until this is decided:

> Do not fetch from that endpoint. Workday roles enter the queue as link-only records.
> Constraint 3 governs — a source whose status is unclear is treated as disallowed
> until checked.

Build Greenhouse, Lever, and Ashby first. Revisit Workday once the pipeline works and
the real size of the gap is visible rather than assumed. Two paths are worth weighing
then: a licensed aggregator that already indexes Workday-posted roles, or a
per-company allowlist built from each tenant's robots.txt and terms.

**Which aggregator API** to use for breadth — and whether it also turns out to be the
legitimate path to Workday-posted roles.

**Whether hosting ever happens.** Revisit only if the local tool earns it.

---

## Deferred features — recorded, not scheduled

Ideas worth keeping, deliberately not built yet. Recorded here so they aren't lost,
and so nobody starts one thinking it is in scope.

- **Pathway / gap tool** — given a specific company, what a resume would need in order
  to be competitive there: which skills, projects, or experience are missing.
- **Alumni finder** — people from the resume's school who work at a target company.

> On the alumni finder specifically: the obvious data source is LinkedIn, and
> constraint 2 forbids it. That is not a detail to be discovered mid-implementation. If
> this is ever built, the data has to come from somewhere permitted — the school's own
> alumni directory or career platform, an opt-in export, or information the user
> supplies. If no permitted source exists, the feature doesn't get built.

---

## Bootstrap — remove this section once the stack decision lands

One-time kickoff prompt. Paste it in plan mode, before any code is written. Once a
stack is approved and recorded above, delete this section — it is stale context
every session after that.

```
I'm building a job-search copilot — a local tool that takes a resume and a few
declared interests, finds matching roles, drafts a cover letter, and queues each
application for me to approve and submit. Read CLAUDE.md first; it's the constitution
for this project, especially the "no unattended submission" and "legitimate data
sourcing only" constraints, which are non-negotiable. The Build order, Decided, and
Open questions sections are already filled in — don't re-ask what's settled there.

Scope for this first pass is the MVP in Build order, and nothing beyond it: discover →
score → queue → I approve → I submit, plus a cover-letter drafter. Resume review and
per-role tailoring are explicitly later; don't design around them, and don't scaffold
them. Resumes in the MVP are selected, not rewritten.

Settled already: local-first, one user at a time, no hosting. Profile-agnostic — no
role family or employer is hardcoded; targeting comes from uploaded resumes plus
declared careers, industries, and locations. Greenhouse, Lever, and Ashby public JSON
APIs first, plus one aggregator for breadth. Workday is deferred as an open Tier 1
question — do not design around fetching from it. BENCHMARK_PROFILE.md holds a real
search to evaluate the matcher against; treat it as test data, not as defaults.

What I need from you, before writing any code:

- Propose 2–3 stack options consistent with local-first — e.g. a Python CLI or small
  local service plus SQLite and a simple local web UI. If you want to argue for
  something heavier, justify it against a single user running this on their own
  machine.
- Propose how the review queue should work. This is the MVP's central mechanic, so
  design it before touching the matching algorithm: what a queue entry holds, how
  link-only entries behave when a posting can't be pulled, how recency and fit combine
  in the ordering, and what the approve/reject/submit step actually looks like.
- Propose how resumes and interests get ingested — parsing a resume into a structured
  profile, and how I declare target careers, industries, and locations.
- Recommend which aggregator API to start with, and say what it does and doesn't
  cover.

Perplexity's Sonar API is for company research and fit-qualification, not for pulling
structured listings — don't route the core ingestion through it.

Explicitly do NOT implement, scaffold, or leave TODOs for autonomous submission,
headless-browser automation against LinkedIn/Indeed/Glassdoor, or any
CAPTCHA/bot-detection bypass. If a stack option requires any of that to be useful,
reject it and say so.

Stay in plan mode until I approve a direction.
```

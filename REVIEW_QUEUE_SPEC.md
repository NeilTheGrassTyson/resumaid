# Review queue specification

The human-approval step, specified. Per `CLAUDE.md` Tier 1, this is the one piece worth
treating as a real spec at solo scale, because it is the safety valve for **constraint 1:
no unattended submission**.

Scope: MVP Stage 1. Cover letters (Stage 2) are hooked but not built here; resume review and
per-role tailoring are out of scope entirely.

---

## 1. What the queue is for

The tool finds and prepares. A person decides and sends. The queue is the surface where that
handoff happens, and it has three jobs:

1. Show a small number of genuinely good roles, ordered so the best use of the next ten minutes
   is at the top.
2. Make the reason each role is present **legible** — a score with no explanation is noise, and
   an unexplained queue trains you to rubber-stamp it.
3. Make approving cheap and submitting deliberate. Those are different actions and the queue
   never conflates them.

A queue that is fast to triage but produces mediocre applications has failed. So has one that is
accurate but so slow to work through that it goes unread.

---

## 2. The entry

One entry is one posting considered for this user. It is created by the pipeline and mutated
almost exclusively by human action.

### 2.1 Identity and provenance

| Field | Notes |
|---|---|
| `id` | Local surrogate key. |
| `source` | `greenhouse` \| `lever` \| `ashby` \| `adzuna` \| `usajobs` \| `manual` |
| `source_job_id` | The id in that source's namespace. Unique with `source`. |
| `dedupe_key` | Normalized `company + title + location`. Used to collapse the same role seen through several sources. |
| `first_seen_at` | When this tool first saw it. Never updated. |
| `last_seen_at` | Refreshed each run the posting is still present. Drives `expired`. |
| `provenance_note` | Human-readable, e.g. "surfaced via Adzuna; ATS record not available". |

When the same `dedupe_key` arrives from several sources, the entry keeps the record from the
highest-priority source: direct ATS (`greenhouse`/`lever`/`ashby`) over aggregator
(`adzuna`/`usajobs`), because the ATS record carries the full description. Lower-priority
duplicates are recorded in `also_seen_in` and do not create entries.

### 2.2 The posting

| Field | Notes |
|---|---|
| `company`, `title`, `locations[]`, `remote` | |
| `posted_at` | Nullable. |
| `posted_at_precision` | `exact` \| `approximate` \| `unknown`. See §5.2 — sources differ badly here and pretending otherwise corrupts the ordering. |
| `apply_url` | Where the human goes to apply. |
| `department`, `employment_type`, `compensation` | Nullable; whatever the source gave. |
| `description_text` | Plain text. Null for link-only. |
| `completeness` | `full` \| `partial` \| `link_only`. See §4. |

### 2.3 Match result

| Field | Notes |
|---|---|
| `fit_score` | 0–100. |
| `score_breakdown` | JSON. Per dimension: subscore, weight, and the **evidence string** that produced it. |
| `matched_signals[]`, `missing_signals[]` | Short human-readable phrases, for the "why" pane. |
| `hard_filter_results` | Which hard filters passed or failed, and on what value. |
| `score_confidence` | `high` \| `medium` \| `low`. Driven by `completeness`. |
| `recency_factor`, `rank_score` | See §5. |
| `oa_expected`, `oa_expectation_confidence`, `oa_expectation_evidence[]` | See §7. |

### 2.4 Resume selection

| Field | Notes |
|---|---|
| `recommended_resume_id` | One of the user's uploaded documents. |
| `selection_rationale` | One sentence, referencing the emphasis that won. |
| `runner_up_resume_id` | Offered as a one-key switch in the UI. |

The tool **selects among documents the user wrote**. It does not rewrite, merge, or generate a
resume. That is a later phase and nothing here anticipates it.

### 2.5 Review and submission

| Field | Notes |
|---|---|
| `state`, `state_changed_at` | See §3. |
| `decision_note` | Free text from the human. |
| `rejection_reason` | Enum + optional free text. See §6.2. |
| `snooze_until` | Set by snooze. |
| `submitted_at`, `submission_channel`, `confirmation_note` | Written only by the human action in §6.4. Handed off to the `applications` log. |
| `cover_letter_id` | Nullable. Stage 2 hook. Nothing writes it in Stage 1. |

---

## 3. States

```
                    ┌──────────────┐
                    │  discovered  │  pipeline created it
                    └──────┬───────┘
              gate fail ┌──┴──┐ gate pass
                        ▼     ▼
                 ┌──────────┐ ┌────────┐
                 │ filtered │ │ queued │  awaiting human triage
                 └──────────┘ └───┬────┘
                                  │
              ┌──────────┬────────┼─────────┬──────────┐
              ▼          ▼        ▼         ▼          ▼
        ┌──────────┐ ┌─────────┐ ┌───────┐ ┌─────────┐ (posting gone
        │ approved │ │rejected │ │snoozed│ │ expired │  or aged out)
        └────┬─────┘ └─────────┘ └───┬───┘ └─────────┘
             │                       │ wakes at snooze_until
             │ human records it       └──────► queued
             ▼
        ┌───────────┐
        │ submitted │  terminal. human-written only.
        └───────────┘
```

| State | Meaning |
|---|---|
| `discovered` | Ingested, not yet scored. |
| `filtered` | Failed a hard filter or the fit floor. **Retained, not deleted** — this is how you audit what the gate threw away. Hidden from the default view. |
| `queued` | Cleared the bar. Awaiting the human. |
| `approved` | The human said yes. The tool prepares materials. **Nothing is sent.** |
| `rejected` | The human said no, with a reason. |
| `snoozed` | Deferred to `snooze_until`, then returns to `queued`. |
| `expired` | Not seen in N runs, or past a closing date. |
| `submitted` | The human applied and recorded it. Terminal. |

Illegal transitions raise. The transition table is data, in one place, and the test suite walks
every pair.

### 3.1 The constraint-1 invariant

This is the load-bearing part of the spec.

- **`approved` ≠ submitted.** Approving triggers no network call to any employer, ATS, or form.
  It prepares: it resolves the resume path, opens the posting for the human, and moves the entry
  to the ready tray.
- **Exactly one function writes `submitted`.** It takes an explicit `actor="human"` argument and
  is reachable only from the UI action and its CLI twin. No scorer, adapter, scheduler, or
  background task can call it.
- **Three tests enforce it**, and they are not optional:
  1. A full pipeline run (`discover → score → queue`) over fixtures produces **zero** writes to
     `submitted_at` and zero `submitted` transitions.
  2. The pipeline makes **no outbound HTTP request** to any host outside the permitted-source
     allowlist. Employer application endpoints are never contacted.
  3. The `submitted` transition rejects any call whose actor is not human.

If a future change makes any of these fail, the change is wrong. The tests are the mechanism by
which "the tool never submits on its own" is a property of the code rather than a promise in a
README.

---

## 4. Link-only and partial entries

Per `CLAUDE.md`: when a posting cannot be pulled from a permitted source, a record holding the
company and a link is a **valid queue entry**. Partial coverage beats reaching for a source that
isn't permitted. In practice this is mostly Workday, which is a deferred open question and is
never fetched from.

| `completeness` | What it means | Confidence |
|---|---|---|
| `full` | Full description text from a permitted source, or pasted by the human. | `high` |
| `partial` | A snippet only (typical of an aggregator). | `medium` |
| `link_only` | Company, title, URL; no description obtainable from a permitted source. | `low` |

Rules:

1. **Never fabricate.** A missing description is shown as missing. The tool does not infer,
   summarize from the title, or fill the gap from another company's posting.
2. **Visible provenance.** The entry displays its `provenance_note` and a badge. It never
   presents as a full record.
3. **Scored on what exists**, with `score_confidence` set accordingly and the score displayed
   with its confidence rather than as a bare number. §5.3 applies the discount.
4. **Paste-to-upgrade.** The primary action on a link-only entry: the human opens the posting,
   copies the description, pastes it in. The entry becomes `full`, re-scores at full confidence,
   and records that the text was human-supplied. This is the permitted path around the Workday
   gap and it must be one keystroke (`p`), not a form.
5. **No Stage 2 drafting from thin data.** The cover-letter drafter will refuse a `link_only`
   entry. Generic input produces generic letters, which is the exact failure voice fidelity is
   defined against.

---

## 5. Ordering

Two stages, deliberately not one blended number.

### 5.1 The gate — fit filters, per constraint 5

Applied in order; first failure stops evaluation and records which filter failed.

1. **Hard filters** (pass/fail): degree level, location/remote compatibility, work authorization
   and clearance eligibility, seniority band, employment type, explicit company and keyword
   exclusions.
2. **Already applied**: a matching company + normalized title in the applications log ⇒ filtered
   as `already_applied`. See §7.3.
3. **Fit floor**: the global floor, or the declared per-family floor where the matched role
   family sets a higher one (a low-priority industry is *reachable but held to a higher bar*,
   not merely ranked lower).

Everything that fails lands in `filtered` with the reason recorded. **The floor never moves to
fill a quota.** If three roles clear it today, three get queued. Constraint 5 outranks the
throughput setting.

### 5.2 The rank

Among survivors:

```
rank_score        = fit_score × recency_factor × confidence_factor

recency_factor    = floor + (1 - floor) * exp(-age_days / τ)      floor = 0.75, τ = 21 days
confidence_factor = high 1.00 | medium 0.92 | low 0.85
```

Recency is **multiplicative and bounded**, not additive. Two properties matter, and the shape of
the curve is chosen to get both:

- **It decays toward the floor rather than being clipped at it.** A clipped exponential with a
  short τ reaches its floor within a few days and then stops distinguishing a one-week-old
  posting from a three-month-old one, which defeats the purpose. This curve still separates
  them: 3d → 0.97, 14d → 0.88, 30d → 0.81, 60d → 0.76.
- **The floor bounds how much recency can do.** Because the factor never falls below 0.75,
  recency can overcome a fit gap of at most **1/0.75 ≈ 33%**. An 85-fit role two months old
  still outranks a fresh 62. Comparable roles reorder freely; a genuinely stronger role cannot
  be buried by a fresher weaker one.

That bound is the honest version of "recency counts, but the fit bar does not move". No
multiplier below 1.0 can prevent *every* inversion — if it did, recency would have no effect at
all — so the design states the gap it permits and enforces it in the tests. An additive bonus
permits an unbounded inversion, which is the failure constraint 5 names.

τ = 21 days: applications land better before a posting has collected hundreds of responses.
Both τ and the floor are tunables, not laws.

`posted_at` is unreliable across sources — Greenhouse exposes `updated_at` rather than a true
creation date, Lever gives `createdAt`, aggregators vary. So:

| `posted_at_precision` | Age used |
|---|---|
| `exact` | Actual age. |
| `approximate` | Actual age, flagged in the UI. |
| `unknown` | 14 days (recency_factor ≈ 0.37 → clamped to 0.60), flagged. |

For sources with no creation date, `first_seen_at` becomes a usable proxy **after** the first
run — everything looks new on day one, and the UI says so rather than pretending otherwise.

### 5.3 Diversity — breadth counts

After ranking, a diversity pass caps any single company at **2 entries** in a day's slate and
interleaves so the top of the queue is not five roles at one employer. Surplus entries stay
`queued` and surface on later days.

### 5.4 The daily slate

```
slate_size = ceil(submissions_per_day × surface_multiplier)
```

Default `submissions_per_day` = 5, `surface_multiplier` starts at 2.5. The multiplier retunes
off the rolling 14-day approval rate:

```
surface_multiplier = clamp(1 / approval_rate, 1.5, 4.0)
```

The gate sits upstream of all of it. A thin day stays a thin day: the slate is a **ceiling on
what is shown**, never a quota to be filled.

---

## 6. The review step

### 6.1 The triage view

One entry at a time. Three panes:

- **Posting** — title, company, location, posted date (with its precision), compensation if
  given, description. Link-only entries show the provenance note and the paste box.
- **Why this is here** — `fit_score` with its confidence, the dimension breakdown with the
  evidence behind each subscore, matched signals, and missing signals. The pane answers "why am
  I looking at this?" without the human opening a database.
- **Materials** — the recommended resume with its rationale and a one-key switch to the runner-up.
  The OA expectation sits here, since it is information about cost.

### 6.2 Actions

| Key | Action |
|---|---|
| `a` | Approve → ready tray |
| `x` | Reject (prompts for reason) |
| `s` | Snooze (1d / 3d / 1w) |
| `o` | Open posting in browser |
| `p` | Paste description (upgrades link-only, re-scores) |
| `r` | Switch to runner-up resume |
| `j` / `k` | Next / previous |
| `u` | Undo last decision |

Rejection reasons are a short closed enum plus optional free text:
`wrong_seniority`, `wrong_location`, `wrong_industry`, `not_this_company`, `already_applied`,
`stale_posting`, `compensation`, `other`.

These are the only honest signal for tuning weights. They feed a `resumaid report weights`
summary the human reads. **Nothing auto-tunes the scoring behind your back** — a matcher that
silently drifts toward what you clicked yesterday is not debuggable, and constraint 5 needs the
bar to be a decision, not an emergent property.

Every action has a CLI twin (`resumaid queue approve <id>`, `reject`, `snooze`, …) calling the
same service function, so the loop is scriptable and testable without a browser.

### 6.3 The ready tray

Approved entries collect here. For each, the tray:

- opens the `apply_url` in the browser on request,
- shows the selected resume's file path with copy-path and reveal-in-folder,
- shows the OA expectation, so a likely two-hour assessment is known before the slot is spent,
- and waits.

The human fills the employer's form. **The tool does not touch it** — no auto-fill, no field
mapping, no form POST. That is constraint 1 and it is not negotiable at any scale.

### 6.4 Recording the submission

Returning from the employer's site, the human clicks **"I submitted this"**. That action:

1. transitions the entry to `submitted` with `actor="human"`,
2. stamps `submitted_at` and asks for `submission_channel`,
3. writes the durable row in the `applications` log (§7).

Anything sitting in `approved` for more than 24 hours raises a reconciliation prompt on the next
session: *did this actually go out?* — with **Yes**, **Not yet**, and **I changed my mind**
(→ `rejected`). Without it, `approved` silently becomes a graveyard and the throughput numbers
stop meaning anything.

---

## 7. The applications log

A separate `applications` table, one row per submission, written at the `submitted` transition.
Separate from the queue on purpose: after submission the lifecycle diverges — the queue is about
triage, the log is about outcomes — and the log must **outlive the posting**. Company, title,
location, and URL are copied, not referenced, because postings get pulled down upstream and a
history that goes blank when a job closes is worthless.

### 7.1 Row

```
id, queue_entry_id (nullable FK), company, title, location, source, apply_url,
submitted_at, submission_channel, resume_used, cover_letter_id (null in Stage 1),
fit_score_at_submit,
oa_expected, oa_expectation_confidence, oa_expectation_evidence,
oa_received, oa_received_at, oa_platform, oa_due_at, oa_completed_at,
outcome, outcome_at, last_touched_at, notes
```

`outcome` ∈ `pending | oa | interview | offer | rejected | ghosted | withdrawn`.

Editing a row is a primary feature, not an afterthought: outcomes arrive by email days later and
must be recordable in two clicks. `ghosted` is set automatically from `pending` after a
configurable silence window (default 30 days) — the only status the tool infers on its own, and
it is reversible.

### 7.2 Anticipating an online assessment

`oa_expected` ∈ `likely | possible | unlikely | unknown`, always with evidence. Three signals, in
descending weight:

1. **Your own history.** An OA previously recorded from this company is the strongest available
   evidence. Weaker: this ATS plus this role family. Learned at runtime from your data.
2. **The posting text.** Deterministic phrase extraction — "coding assessment", "take-home",
   "technical screen", "timed challenge", named platforms — each hit stored as a quoted span with
   its sentence, so the prediction is auditable rather than oracular.
3. **Optional company research.** A Perplexity Sonar lookup, cached per company with a timestamp.
   This is Sonar in its sanctioned role — company research, never listing ingestion. Off by
   default; opt in per run.

**Deliberately not shipped:** any hardcoded company-to-OA table. `CLAUDE.md` forbids hardcoding
employers, and a stale table is worse than no prediction. The expectation is also shown on the
queue entry before submission, since it is information about cost.

### 7.3 Duplicate guard

Before queueing, the pipeline checks the log for the same company + normalized title. A match
filters the entry as `already_applied` rather than re-surfacing it. Re-surfacing roles you have
already applied to is the most common way a daily job-search tool becomes untrustworthy.

### 7.4 Export

`resumaid export applications --format csv` and a **Download CSV** button on the Log tab.
UTF-8 **with BOM**, ISO-8601 dates, flat one-row-per-application, human-readable headers — so a
double-click opens it in Excel with encoding and dates intact and it is pivot-table-ready without
cleanup. `--format xlsx` is a convenience extra; CSV is the contract.

---

## 8. What this spec forbids

Restated here because the queue is where pressure to violate them would appear:

- No automated submission, of any kind, behind any flag, under any framing.
- No auto-filling an employer's application form.
- No storing credentials, cookies, or session tokens for an employer or ATS.
- No headless-browser automation against platforms whose terms prohibit it.
- No CAPTCHA solving or bot-detection evasion.
- No fetching from the undocumented Workday tenant endpoint while that question is open.

A request to add any of these is a Tier 1 conversation and, for most of them, a refusal.

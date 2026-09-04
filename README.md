# resumaid

A personal job-search copilot. It finds roles that fit, scores them against your own resumes and
declared interests, and puts what clears the bar into a review queue — with the best-fitting
resume already named and a legible reason it's there.

**It never submits an application.** You read the queue, approve what's worth your time, apply
on the employer's site yourself, and record it. That is the design, not a limitation: see
`CLAUDE.md` for the constraints that govern this project, and `REVIEW_QUEUE_SPEC.md` for how the
review step works.

Local-first and single-user. Your resumes and application history stay on your machine.

---

## Getting started

```bash
uv venv && uv pip install -e '.[dev]'
cd ui && npm install && npm run build && cd ..   # builds the review UI, once

resumaid init        # creates ~/.resumaid
resumaid serve       # http://127.0.0.1:8765 — go to the Setup tab
```

Everything after installing is doable in the browser: drop in your resumes, say what you're
looking for, add job boards, run discovery, triage the queue, and record what you submit. The
CLI does all of the same things if you prefer it — every browser action has a command, and both
write the same files.

<details>
<summary>Or set it up entirely from the command line</summary>

```bash
resumaid resume add ~/resumes/master.pdf --master
resumaid resume add ~/resumes/defense.pdf
resumaid interests edit                # opens ~/.resumaid/interests.yaml
resumaid profile edit                  # check what the parser read from your resumes
resumaid board add https://boards.greenhouse.io/somecompany
resumaid run
```
</details>

`resumaid serve` refuses to start without a built UI rather than serving a blank page — pass
`--build` to build it for you, or `--api-only` to skip it. On Windows, if VS Code auto-activates
a different project's virtualenv in every terminal, name the interpreter explicitly so the
install cannot land in the wrong project:

```powershell
uv venv
uv pip install --python .\.venv\Scripts\python.exe -e ".[dev]"
```

Nothing is assumed about what you're looking for. There is no built-in idea of which roles are
worth having — targeting comes entirely from your resumes plus what you declare.

## The loop

**Discover.** `resumaid run` polls the ATS boards you've registered plus, if you've configured
credentials, Adzuna and USAJobs. Aggregator hits that point at a known ATS register that board
automatically, so coverage compounds: today's snippet is tomorrow's full posting. See
`DATA_SOURCES.md`.

**Score.** Hard filters first — location, seniority, degree, clearance, exclusions, and whether
you've already applied. Then a fit score across role family, skills, seniority, location and
industry, each subscore carrying the evidence that produced it. Everything below the bar is
filtered, not merely ranked low, and kept so you can audit what the gate threw away
(`resumaid queue filtered`).

Ranking is `fit × recency × confidence`. Recency reorders comparable roles but is bounded: it
can overcome a fit gap of about 33%, never more. A per-company cap keeps one employer from
filling the slate.

**Location** is a real input, not a keyword match. Your home comes from your resume's contact
block (override it with `locations.home`), and a bundled table of 1,000 US places gives actual
distances — so a role 41 miles away scores like the commute it is even if it's over a state
line. Name cities and states with weights, the way role families work:

```yaml
locations:
  remote: true
  home: "Boston, MA"        # defaults to whatever your resume says
  max_distance_miles: 50    # inside this is local; null turns proximity off
  places:
    - {place: "Boston, MA", weight: 1.0}
    - {place: "Denver, CO", weight: 0.7}
    - {state: "CO", weight: 0.5}
  relocation: "no"          # no | willing | preferred
```

A weight only raises a location's score — to rule somewhere out, don't name it. With
`relocation: "no"`, anything beyond the radius is filtered rather than ranked low; a place the
table can't resolve is never filtered, only discounted, so nothing disappears for a reason you
can't see. No geocoding API is called: this works offline, and your home city never leaves the
machine.

**Review.** `resumaid serve`, or the CLI. Keyboard-driven: `j`/`k` move, `a` approves, `x`
rejects with a reason, `s` snoozes, `p` pastes in a description the tool wasn't allowed to
fetch, `o` opens the posting.

**Submit — you.** Approving moves an entry to the ready tray with the resume path and a link. You
apply, come back, and record it. That row lands in the application log.

## The application log

Every submission is recorded durably: company, position, when, how, which resume, and what came
back. Company and title are copied rather than referenced, so your history survives the posting
being taken down.

```bash
resumaid app log
resumaid app update 12 --outcome interview
resumaid app update 12 --oa --platform HackerRank
resumaid export --out ~/applications.csv          # UTF-8 with BOM; opens cleanly in Excel
resumaid export --format xlsx --out ~/apps.xlsx   # needs the 'xlsx' extra
```

Three things fall out of keeping it. Roles you've already applied to stop being re-surfaced. The
daily slate sizes itself against your real approval rate. And answering *did an assessment
arrive?* teaches the online-assessment prediction — which starts as quoted phrases from the
posting and becomes, over a few dozen applications, your own data. No employer is hardcoded
anywhere; if the tool doesn't know, it says `unknown`.

## Commands

| | |
|---|---|
| `resumaid init` | Create the data directory and interests template |
| `resumaid resume add <file> [--master]` | Register a resume; re-parses your profile |
| `resumaid resume list \| remove \| master <id>` | Manage your resumes |
| `resumaid interests edit \| show` | What you're looking for |
| `resumaid profile edit \| reparse` | The profile parsed from your resumes |
| `resumaid board add <url\|token>` | Register an ATS board to poll |
| `resumaid board list \| remove \| enable <id>` | Manage boards |
| `resumaid run [--llm] [--research-oa]` | Discover, score, queue |
| `resumaid queue list \| show <id> \| filtered` | Read the queue |
| `resumaid queue approve \| reject \| snooze \| paste <id>` | Triage |
| `resumaid ready` | Approved, awaiting your submission |
| `resumaid submitted <id> [--channel …]` | Record that you applied |
| `resumaid app log \| update <id>` | The application history |
| `resumaid export [--format csv\|xlsx]` | Export the history |
| `resumaid status` | Where everything stands |
| `resumaid serve [--build] [--api-only]` | The review UI on localhost |

## Your data

Everything lives in `~/.resumaid/` (mode 0700), outside this repository:

```
resumaid.db          queue, applications, boards, run history
resumes/             your resume files
profile.yaml         parsed from them, then yours to correct
interests.yaml       what you're looking for
boards.yaml          ATS boards, hand-added and auto-discovered
secrets.env          API keys (0600)
```

Nothing leaves the machine beyond the API calls needed to find and score roles. With `--llm`, a
near-the-bar posting is sent along with a skills-and-degree summary for adjudication — never a
resume file, never contact details, and the payload is checked for PII before it goes.

## Development

```bash
pytest                       # 103 tests
pytest -m live               # opt-in; hits one real public board
ruff check src tests
cd ui && npm install && npm run build     # SPA; served by `resumaid serve`
cd ui && npm run types                    # regenerate API types from the OpenAPI schema
```

`ui/src/api/types.ts` is generated from the FastAPI schema — don't edit it by hand.

The tests in `tests/test_constraint_one.py` exist to keep the tool honest: they assert that no
pipeline, scorer, adapter or background task can reach the `submitted` state, that a full run
writes zero submissions, and that the database itself refuses a submission with no human action
logged against it. If a change makes those fail, the change is wrong.

## Where things are written down

- **`CLAUDE.md`** — the constitution. Five non-negotiable constraints, the build order, and what's
  settled or deliberately open.
- **`REVIEW_QUEUE_SPEC.md`** — the review step in full: entry fields, states, ordering, link-only
  behavior, and the approve/submit boundary.
- **`DATA_SOURCES.md`** — every source, its limits, and why it's permitted. Also why Workday
  isn't.
- **`docs/adr/`** — the design decisions, each with the alternatives it beat and why.
- **`BENCHMARK_PROFILE.md`** — a real search used to evaluate the matcher. Test data, never
  defaults.

## Not built

Cover letters are MVP stage 2; resume review and per-role tailoring come after. Nothing here
scaffolds them.

Not built at all, and not going to be: autonomous submission, form auto-fill, headless-browser
automation against platforms that prohibit it, or anything that evades bot detection.

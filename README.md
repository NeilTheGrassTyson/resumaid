# resumaid

A job-search assistant that runs on your own computer.

It checks company job boards for new openings, scores each one against your résumé and what
you've said you're looking for, throws out the poor fits, and puts the rest in a queue for you to
look through. For each one it tells you *why* it's there and which of your résumés to send.

**It never applies to anything for you.** You read the queue, pick what's worth your time, apply
on the company's own website yourself, and then tell resumaid you did. That's on purpose:
applications fired off automatically get flagged as spam by hiring systems, which hurts your
response rate. A human in the loop is what makes it work.

Everything stays on your computer. Your résumés, your application history, all of it. There's no
account to make and nothing gets uploaded anywhere.

---

# Installing it

**No programming knowledge needed.** You'll copy and paste a few commands. Budget about 15
minutes, most of it waiting for downloads.

You do **not** need VS Code, or any other code editor.

## Step 1 — Install Python

Python is the language resumaid is written in. Your computer needs it to run.

**Windows:** Download it from **[python.org/downloads](https://www.python.org/downloads/)** and
run the installer.

> ⚠️ **On the first screen, tick the box that says "Add python.exe to PATH"** — it's at the
> bottom and it's easy to miss. Without it, none of the commands below will work. Then click
> "Install Now".

**Mac:** Download from **[python.org/downloads](https://www.python.org/downloads/)** and run the
installer. (Macs come with an older Python that won't work here, so install this one even if you
think you have it.)

You need version **3.11 or newer**. The download button on that page always gives you something
current.

## Step 2 — Install Node.js

Node builds the visual interface you'll actually use.

Download the **LTS** version from **[nodejs.org](https://nodejs.org/)** and run the installer.
Accept all the defaults. You want version **20 or newer**.

## Step 3 — Restart your terminal

The two installers above change settings that only take effect in a **new** window.

- **Windows:** Press `Win`, type `powershell`, open **Windows PowerShell**.
- **Mac:** Press `Cmd + Space`, type `terminal`, open **Terminal**.

If you already had one open, close it and open a fresh one.

Check both installs worked by typing these two lines, pressing Enter after each:

```
python --version
node --version
```

You should see version numbers like `Python 3.13.4` and `v22.11.0`. If either says something
like *"not recognized"* or *"command not found"*, jump to
[Something went wrong](#something-went-wrong) below.

## Step 4 — Download resumaid

On this page, click the green **`< > Code`** button near the top, then **Download ZIP**.

Unzip it somewhere you'll remember — your Desktop or Documents folder is fine. You'll get a
folder called `resumaid-main` or similar.

## Step 5 — Open a terminal in that folder

You need your terminal pointed at the folder you just unzipped.

**Windows:** Open the folder in File Explorer. Click the address bar at the top (where the folder
path is shown), type `powershell`, and press Enter.

**Mac:** Open Terminal, type `cd ` (with a space after it), then **drag the folder from Finder
into the Terminal window** — it fills in the path for you. Press Enter.

To confirm you're in the right place, type `dir` (Windows) or `ls` (Mac). You should see files
including `README.md` and `pyproject.toml`.

## Step 6 — Install

Copy this whole block, paste it into your terminal, and press Enter. On Windows you may be asked
to confirm the paste — say yes.

**Windows:**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

**Mac:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

<details>
<summary>What did that just do?</summary>

It made a private folder called `.venv` inside the project and installed resumaid's building
blocks into it. Nothing was installed system-wide, so this can't interfere with anything else on
your computer. Deleting the project folder removes it completely.

The Windows `Set-ExecutionPolicy` line lets the activation script run **in that one window only**.
It resets when you close the terminal and changes nothing permanently.
</details>

Then build the interface — this takes a minute or two and prints a lot of text, which is normal:

```
cd ui
npm install
npm run build
cd ..
```

## Step 7 — Start it

```
resumaid init
resumaid serve
```

Open **http://127.0.0.1:8765** in your browser. Go to the **Setup** tab and you're ready.

---

# Using it day to day

**Every time you want to use resumaid**, open a terminal in the project folder and run:

**Windows**

```powershell
.\.venv\Scripts\Activate.ps1
resumaid serve
```

**Mac**

```bash
source .venv/bin/activate
resumaid serve
```

Then open http://127.0.0.1:8765. To stop it, press `Ctrl + C` in the terminal.

> If Windows says the activation script is blocked, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` first, then try again.

## First-time setup, in the browser

On the **Setup** tab, in order:

1. **Drop in your résumé.** PDF, Word, or plain text. If you keep several versions tailored to
   different kinds of job, add them all — resumaid picks the best fit for each opening and tells
   you why. It never rewrites them. Mark your longest, most complete one as the "master".
2. **Check what it read.** Expand *"What was read from them"* and fix anything wrong. This is what
   your job matches are scored against, so it's worth a minute.
3. **Say what you're looking for.** Add role families ("mechanical engineering", "product
   marketing") with a few keywords each. Set where you'll work — your home city, how far you'd
   commute, whether you'd take remote or relocate.
4. **Add some job boards.** Paste the careers-page link for companies you'd like to work at. It
   works with links that look like `boards.greenhouse.io/company`, `jobs.lever.co/company`, or
   `jobs.ashbyhq.com/company`. Boards also add themselves over time as roles turn up.

Then click **Run discovery**. Anything that clears your bar lands in the **Queue** tab.

## The daily rhythm

**Queue** — one role at a time. It shows the posting, why it scored what it did, and which résumé
to send. Approve the good ones, reject the rest (say why — it helps tune things later).

`j` and `k` move, `a` approves, `x` rejects, `o` opens the posting in a new tab.

**Ready to submit** — your approved roles, each with a link and the résumé file to attach. **You
apply on the company's own site.** Come back and click *"I submitted this"*.

**Applications** — everything you've sent, what came back, and whether a coding test or
assessment showed up. Edit any cell directly. Download it as a spreadsheet whenever you like.

A quiet day is a real answer. If only three roles are good enough, you get three — the bar doesn't
drop to fill a quota.

---

# Something went wrong

<details>
<summary><b>"python is not recognized" / "command not found: python"</b></summary>

Python either isn't installed, or the "Add python.exe to PATH" box wasn't ticked during install.

Re-run the installer from [python.org](https://www.python.org/downloads/), choose **Modify** (or
uninstall and reinstall), and make sure that box is ticked. Then **close and reopen your
terminal**.

On Mac, try `python3` instead of `python` — Macs sometimes only recognise that name.
</details>

<details>
<summary><b>"npm is not recognized" / "command not found: npm"</b></summary>

Node.js isn't installed, or your terminal was open before you installed it. Install it from
[nodejs.org](https://nodejs.org/), then **close and reopen your terminal**.
</details>

<details>
<summary><b>"uv is not recognized"</b></summary>

You're following older instructions. `uv` is an optional tool you don't need — use the commands
in Step 6 above, which use Python's built-in installer instead.
</details>

<details>
<summary><b>Windows: "running scripts is disabled on this system"</b></summary>

Windows blocks scripts by default. Run this first, then retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

It only applies to that one terminal window and resets when you close it.

If you'd rather skip activation entirely, you can call resumaid by its full path instead —
this always works:

```powershell
.\.venv\Scripts\resumaid.exe serve
```
</details>

<details>
<summary><b>"The review UI has not been built yet"</b></summary>

The visual interface needs building once. From the project folder:

```
cd ui
npm install
npm run build
cd ..
```

Or let resumaid do it for you: `resumaid serve --build`
</details>

<details>
<summary><b>The page won't load, or the address is already in use</b></summary>

Make sure the terminal running `resumaid serve` is still open — closing it stops the app.

If something else is already using that address, pick another:

```
resumaid serve --port 8790
```

Then open http://127.0.0.1:8790 instead.
</details>

<details>
<summary><b>My résumé uploaded but nothing was read from it</b></summary>

If your PDF is a scan or photo of a printed page, there's no text in it to read — only an image.
Export a fresh PDF from Word, Google Docs, or Pages instead, or upload the Word file directly.
</details>

<details>
<summary><b>The queue is empty after a run</b></summary>

Usually one of three things:

- **No job boards yet.** Add a few companies on the Setup tab.
- **Nothing cleared the bar.** Check the **Filtered** tab — it lists what was thrown out and why.
  If it's rejecting things you'd have wanted, your settings are too narrow.
- **No role families set.** Without them, resumaid has no idea what counts as relevant.
</details>

---

# Good to know

**Nothing is assumed about what you want.** resumaid has no built-in notion of which jobs are
good. It only knows what your résumé says and what you tell it, so the effort you put into the
Setup tab is the ceiling on how useful the results are.

**Optional: more job listings.** Out of the box, resumaid reads company job boards directly, which
needs no setup. You can also connect two free services for wider coverage —
[Adzuna](https://developer.adzuna.com/) and [USAJobs](https://developer.usajobs.gov/) — by putting
their free API keys in `secrets.env` in your data folder. Entirely optional.

**Some jobs come through as links only.** A few big employers use systems resumaid isn't permitted
to read from, so those show up with just the company, title, and a link. Open the posting, copy
the description, press `p` and paste it in — it re-scores properly. See `DATA_SOURCES.md` for
which sources are used and why.

**Where your files live.** A folder called `.resumaid` in your home directory
(`C:\Users\YourName\.resumaid` on Windows, `~/.resumaid` on Mac) holds your résumés, settings, and
application history. Back it up if you care about it; delete it to start over.

---

# For developers

<details>
<summary><b>Commands, architecture, and development setup</b></summary>

## Commands

Everything in the browser has a command-line equivalent, calling the same code.

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

## Your data

Everything lives in `~/.resumaid/` (mode 0700 on POSIX), outside this repository:

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
pytest                       # 295 tests
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

If you use [uv](https://docs.astral.sh/uv/), `uv venv && uv pip install -e ".[dev]"` replaces the
venv and pip steps. It isn't required.

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

</details>

## Not built

Cover letters are MVP stage 2; resume review and per-role tailoring come after. Nothing here
scaffolds them.

Not built at all, and not going to be: autonomous submission, form auto-fill, headless-browser
automation against platforms that prohibit it, or anything that evades bot detection.

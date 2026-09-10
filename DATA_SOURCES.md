# Data sources

Which APIs are wired up, what they return, what they cost, and — the part that matters —
the basis on which each one is permitted.

Endpoint specifics live here rather than in `CLAUDE.md`, so they can change without touching
the constitution. Constraint 3 governs everything in this file: public ATS JSON APIs, licensed
aggregator APIs, and Sonar for company research. **A source whose status is unclear is treated
as disallowed until checked.**

The permitted set is enforced in code, not just documented: `ALLOWED_HOSTS` in
`src/resumaid/sources/base.py` is checked before every request, and a request to any other host
raises `DisallowedSource`. Tests assert that Workday, LinkedIn, Indeed, Glassdoor, and arbitrary
company careers hosts are all refused.

---

## Wired up

### Greenhouse — job board API

| | |
|---|---|
| Endpoint | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` |
| Auth | None |
| Basis | Public documented job board API, intended for exactly this |
| Returns | Full description (`content`), title, location, offices, departments, `updated_at`, absolute apply URL |
| Completeness | `full` |
| Adapter | `sources/greenhouse.py` |

The priority source per `CLAUDE.md` — a large share of roles actually post here.

**Two things worth knowing.** `content` comes back **HTML-entity-escaped** (`&lt;p&gt;`), so it
must be unescaped *before* tags are stripped or the markup survives into the text. And the only
date is `updated_at`, not a creation date, so postings are recorded with
`posted_at_precision = approximate`: calling it exact would let an edited old posting pass as
fresh in the ranking.

### Lever — postings API

| | |
|---|---|
| Endpoint | `GET https://api.lever.co/v0/postings/{company}?mode=json` |
| Auth | None |
| Basis | Public postings API backing Lever's own hosted boards |
| Returns | `text` (title), `categories` (team, location, commitment), `descriptionPlain`, `lists`, `createdAt` (epoch ms), `hostedUrl`, `workplaceType` |
| Completeness | `full` |
| Adapter | `sources/lever.py` |

The only source with a genuine creation timestamp, so its postings are `exact` for recency.

### Ashby — public job posting API

| | |
|---|---|
| Endpoint | `GET https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true` |
| Auth | None |
| Basis | Documented public posting API |
| Returns | Title, location plus secondary locations, department, employment type, `publishedAt`, `descriptionPlain` or `descriptionHtml`, compensation tier summary |
| Completeness | `full` |
| Adapter | `sources/ashby.py` |

No server-side filtering or search, so everything is filtered locally. Entries with only
`updatedAt` fall back to `approximate` precision.

### Adzuna — aggregator, for breadth

| | |
|---|---|
| Endpoint | `GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}` |
| Auth | `app_id` + `app_key` (free registration) |
| Rate limit | ~1,000 calls/month on the free tier (~33/day) |
| Basis | Licensed public API with registered credentials |
| Returns | Title, company, location, `created`, salary range, `redirect_url`, **description snippet only** |
| Completeness | `partial` (or `link_only` with no snippet) |
| Adapter | `sources/adzuna.py` |

**What it covers:** broad multi-country indexing across job boards and company sites — the main
way roles are discovered at companies not already in `boards.yaml`.

**What it does not cover:** full descriptions. A two-line teaser is not a posting, so these
arrive at medium confidence and are discounted in the ranking until the description is pasted
in. Also: no ATS metadata, duplicates across sources (handled by `dedupe_key`), and only
incidental Workday coverage — **it does not close the Workday gap.**

The free tier is the binding constraint on breadth. Search terms come from declared role-family
keywords, capped at four per run.

### USAJobs — federal roles

| | |
|---|---|
| Endpoint | `GET https://data.usajobs.gov/api/search` |
| Auth | `Authorization-Key` header + a registered email in `User-Agent` |
| Basis | Official US government API, free and documented |
| Returns | Full structured posting: title, organization, locations, schedule, pay range, publication and close dates, qualification summary, duties |
| Completeness | `full` |
| Adapter | `sources/usajobs.py` |

The one source whose permitted status is not in any doubt. Federal-civilian only, so it deepens
the defense/aerospace lane rather than adding breadth.

Note on PII: this is the only request that carries the user's email address. It goes solely to
the government API that requires it for caller registration, and never accompanies posting or
profile data.

### Perplexity Sonar — company research (opt-in, not wired to ingestion)

Used only for company research and fit-qualification, per `CLAUDE.md` — never to pull listings.
Currently limited to caching an assessment verdict per company in `company_research`, consulted
by the OA predictor when a run passes `--research-oa`. Off by default.

---

## Deliberately not used

### Workday — the open question

Workday is a large share of where applications actually get submitted, and
`BENCHMARK_PROFILE.md` names it as one of the two channels this user's applications have
historically gone through. So this is the biggest coverage gap, and it is left open on purpose.

Workday career sites expose an undocumented JSON endpoint that their own frontend calls. It is
not a published public API, and each tenant carries the **employer's** terms rather than one
central Workday policy — so "is this permitted" has a different answer per company. Constraint 3
says a source whose status is unclear is disallowed until checked.

**Until the founder decides:** nothing fetches that endpoint, no Workday host is on the
allowlist, and Workday roles enter the queue as link-only records. `resumaid queue paste` is the
permitted way to give such an entry a real description. Two paths are worth weighing when this
is revisited: a licensed aggregator that already indexes Workday-posted roles, or a per-company
allowlist built from each tenant's robots.txt and terms.

### LinkedIn, Indeed, Glassdoor

Excluded by constraint 2. No scraping, no headless-browser session automation, no CAPTCHA or
bot-detection handling — under any framing, behind any flag. This also rules out the obvious
data source for the deferred alumni-finder feature; if that is ever built, the data has to come
from a school's own directory, an opt-in export, or the user.

### Aggregators that re-serve scraped platform data

Some RapidAPI-hosted job APIs (JSearch among them) build their index substantially from
platforms whose terms prohibit scraping. That makes their status unclear at best, which
constraint 3 resolves as disallowed. Not used.

### Company careers pages

Not scraped. A per-site robots.txt and terms check would be needed first, and the MVP does not
do one.

---

## The self-feeding board registry

The ATS APIs are per-company, and the tool has no way to know which companies exist. Rather than
making the user curate that list:

When an aggregator result's apply URL points at `boards.greenhouse.io`,
`job-boards.greenhouse.io`, `jobs.lever.co`, or `jobs.ashbyhq.com`, the board token is extracted
and registered. Later runs poll that company's ATS directly — permanently upgrading a snippet
into a full-description source at no extra API cost. `resumaid board add <url>` covers companies
named by hand; `resumaid board list` shows what has accumulated and how each was found.

## Credentials

Stored in `~/.resumaid/secrets.env`, mode 0600, outside the repository. Environment variables
override the file.

```
ADZUNA_APP_ID=…
ADZUNA_APP_KEY=…
USAJOBS_API_KEY=…
USAJOBS_EMAIL=you@example.com
ANTHROPIC_API_KEY=…        # optional: near-the-bar adjudication
PERPLEXITY_API_KEY=…       # optional: company research
```

A source with no credentials configured is skipped silently — the ATS sources need none, so the
tool is useful before any key is set up.

## Adding a source

Adding one is a Tier 1 conversation, not an edit. It means establishing the permitted-use basis
first, then: add the host to `ALLOWED_HOSTS`, write an adapter returning `RawPosting`, record a
fixture in `tests/fixtures/`, test the parse, and document it here with its basis.

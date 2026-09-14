# 0011. Frontend-writable secrets: aggregator keys only, write-only

Status: accepted     Date: 2026-09-14

## Context

CLAUDE.md's Tier list puts "storing any credential, cookie, or session token for a third-party
site" in Tier 1 — a conversation before code, not an edit to just make. Until now that was
resolved by keeping secrets.env CLI/file-only: `resumaid secrets edit` scaffolds it with
registration links and opens it in `$EDITOR`, but the app itself never reads a key value from
the user or writes one.

The user asked for the aggregator keys (Adzuna, USAJobs) to be settable from the Setup tab, as
part of a broader "all configuration should be accessible via the frontend" preference. That's
a real usability gap — everything else (resumes, interests, boards) already lives there — but
it's exactly the Tier 1 case CLAUDE.md calls out, so it gets decided deliberately rather than
just built.

The risk isn't "someone else reads the file" — constraint 4 already accepts local storage for
resumes and PII, and this is a single-user local tool, not multi-tenant. It's that a browser
text field is a worse home for a secret than a file opened in your own editor: it can be
autofilled into the wrong place, land in dev-tools history, or get exposed on a screen-share —
none of which apply to hand-editing a file.

## Decision

The Setup tab gets a Credentials section for exactly the two aggregator keys — Adzuna
(`ADZUNA_APP_ID` + `ADZUNA_APP_KEY`) and USAJobs (`USAJOBS_API_KEY` + `USAJOBS_EMAIL`) — the
pair that actually gates self-registering job boards. It is **write-only**:

- `GET /api/secrets` returns which keys are configured (booleans) — never a value, so nothing
  sensitive that was already saved round-trips back to the browser on page load.
- `PUT /api/secrets` accepts one or more key/value pairs and writes them into secrets.env,
  preserving comments and any keys the request didn't touch (including `ANTHROPIC_API_KEY` and
  `PERPLEXITY_API_KEY`, which stay CLI/file-only per this ADR).
- Form fields always render blank with a "configured" badge next to each key, the same pattern
  as `Board add`'s "leave blank to keep" — you retype a key to change it, you don't edit it in
  place.
- The mutating route gets its CLI twin per ADR 0002: `resumaid secrets set KEY=VALUE [KEY=VALUE
  ...]`, so the same write path is reachable without a browser.
- Nothing here changes `resumaid secrets edit` — the file stays hand-editable, and the two paths
  write the same file in the same format.

## Alternatives considered

- **Keep CLI/file-only (status quo).** Zero additional attack surface — the strongest option on
  that axis alone. Rejected as the default because it fails the user's actual, reasonable
  request: everything else is in the Setup tab, and routing two specific keys through a text
  editor while the rest of setup is a web form is friction with no matching safety story, since
  the file this writes to is the same file `secrets.env edit` already produces.
- **Full reveal or masked preview (e.g. `••••1234`).** More convenient — lets you confirm which
  key is set without guessing, or copy it back out later. Rejected for now because it requires
  the real value to travel back to the browser on request (reveal) or be derivable from what's
  displayed (a masked suffix still confirms guesses); write-only is the smaller exposure for a
  first cut, and easy to loosen later if it's actually missed in practice.
- **All six keys, including the optional LLM ones.** Matches "all configuration" most literally.
  Rejected for scope: `ANTHROPIC_API_KEY` and `PERPLEXITY_API_KEY` aren't blocking anything today
  (constraint 5 already works with the LLM disabled, ADR 0006), so widening the credential
  surface for keys nobody is currently waiting on isn't worth it yet. Revisit alongside Stage 2.

## Consequences

Buys: the Setup tab becomes sufficient for the whole loop that actually blocks discovery working
day one, without a text editor detour. The write-only shape means a compromised browser tab (an
XSS in a dependency, a malicious extension) can *overwrite* a key but never *read* one back out
through this API — a meaningfully smaller blast radius than a reveal-capable form.

Costs: you can't verify a saved key is correct from the Setup tab itself — only that a run
against it succeeds or fails with a clear error. If that turns out to be a real friction point,
the masked-preview alternative above is the natural next step, not a redesign.

## Revisit when

The optional LLM keys want frontend management too (Stage 2, likely, once cover-letter drafting
makes `ANTHROPIC_API_KEY` load-bearing rather than optional), or "no way to verify a saved key"
turns out to be a recurring support question — at which point masked-preview is the smallest
change that answers it. Also revisit if hosting (CLAUDE.md, open questions) ever happens: this
whole design assumes one local user and a file only they can read, which stops being true under
multi-tenancy.

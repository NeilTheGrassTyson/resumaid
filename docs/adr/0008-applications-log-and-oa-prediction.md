# 0008. Applications log as a durable table; OA predicted from runtime data

Status: accepted     Date: 2026-08-31

## Context

The founder asked for a record of which companies have completed applications, for what
positions, when they were submitted, and whether to anticipate an online assessment — exportable
to CSV or openable in Excel.

Two design questions fall out. Where does the history live relative to the queue? And how does
the tool predict an OA without hardcoding employers, which `CLAUDE.md` forbids?

## Decision

**A separate `applications` table, denormalized.** One row written at the `submitted`
transition. Company, title, location, and apply URL are *copied*, not referenced by foreign key.

The queue is about triage; the log is about outcomes. After submission the lifecycle diverges —
`pending → oa → interview → offer/rejected` has nothing to do with queue states — and, more
importantly, the log must outlive the posting. Postings get pulled down upstream; a history that
goes blank when a job closes is worthless.

**OA prediction from three runtime signals**, in descending weight:

1. **The user's own history.** A recorded assessment from this company is the strongest evidence
   available, and it is theirs.
2. **Deterministic phrase extraction** over the posting text — generic hiring vocabulary
   ("coding assessment", "take-home", "timed challenge") and assessment platform names. Each hit
   is stored as a quoted span with its sentence, so the prediction is auditable. Negations mask
   their own span before positives are scanned: "no coding tests" contains "coding test", and
   scanning naively cancels the negation out.
3. **Optional cached company research** via Sonar — its sanctioned role, never listing
   ingestion. Off by default.

The prediction also surfaces on the queue entry *before* submission, since a likely two-hour
assessment is information about cost when deciding whether to spend a slot.

**Export**: CSV, UTF-8 with BOM, ISO-8601 dates, flat and human-headed. xlsx as a convenience.

## Alternatives considered

- **A view over queue entries in `submitted` state.** No second table, no duplication. Rejected:
  it goes blank when a posting is deleted or expires, and it would force post-submission outcome
  fields onto the queue table, where they do not belong.
- **A shipped company-to-OA lookup table.** The fastest path to a useful prediction on day one.
  Rejected on two counts: `CLAUDE.md` states no employer is hardcoded anywhere in this
  repository, and such a table rots silently — companies change their process and the tool keeps
  asserting the old answer with false confidence.
- **An LLM judgment per posting for the OA call.** Rejected as disproportionate: this is phrase
  detection, deterministic phrases do it accurately, and it would send posting text off-machine
  for a low-stakes hint.
- **xlsx as the primary format.** Rejected: CSV is diffable, scriptable, and opens in Excel
  anyway given the BOM. xlsx stays an extra.
- **Foreign-key-only storage with a JOIN for display.** Rejected for the durability reason above.

## Consequences

The log duplicates data that also lives in `queue_entries`, accepted deliberately for
durability. Because the log exists, three things come free: a duplicate guard that stops
re-surfacing roles already applied to, a real approval rate to tune the daily slate against, and
ground truth that makes the OA prediction improve with use rather than staying a keyword
heuristic.

The prediction is weak until the user has recorded a few dozen applications. That is honest —
`unknown` is reported as `unknown` — and it is why recording the outcome is a two-click action
rather than a buried field.

## Revisit when

The user has enough history that history alone dominates, and the phrase list becomes
unnecessary weight; or an outcome type appears that the flat `outcome` enum cannot express.

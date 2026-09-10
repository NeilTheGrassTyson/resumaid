"""The queue state machine, and the constraint-1 guard.

This module is the safety valve for CLAUDE.md constraint 1: the tool prepares applications; a
human clicks send. Everything here exists to make "never submits on its own" a property of the
code rather than a promise in a README.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from resumaid.models import QueueState

#: Who may cause a transition. Only ``human`` reaches SUBMITTED.
HUMAN = "human"
PIPELINE = "pipeline"
SYSTEM = "system"

S = QueueState

#: The legal transitions, in one place, as data. The test suite walks every pair.
TRANSITIONS: dict[QueueState, set[QueueState]] = {
    S.DISCOVERED: {S.QUEUED, S.FILTERED, S.EXPIRED},
    S.QUEUED: {S.APPROVED, S.REJECTED, S.SNOOZED, S.EXPIRED, S.FILTERED},
    S.SNOOZED: {S.QUEUED, S.REJECTED, S.EXPIRED},
    S.APPROVED: {S.SUBMITTED, S.REJECTED, S.QUEUED},
    S.FILTERED: {S.QUEUED},          # re-scoring can rescue an entry (e.g. paste-to-upgrade)
    S.REJECTED: set(),
    S.EXPIRED: set(),
    S.SUBMITTED: set(),              # terminal
}

#: Transitions only a human may cause. This is the list constraint 1 turns on.
HUMAN_ONLY: set[tuple[QueueState, QueueState]] = {
    (S.QUEUED, S.APPROVED),
    (S.QUEUED, S.REJECTED),
    (S.SNOOZED, S.REJECTED),
    (S.APPROVED, S.SUBMITTED),
    (S.APPROVED, S.REJECTED),
    (S.APPROVED, S.QUEUED),
}


class IllegalTransition(ValueError):
    """The state machine refused a transition."""


class UnauthorizedActor(PermissionError):
    """A non-human actor tried to cause a human-only transition.

    Raised rather than returned. A caller that reaches this has a bug that constraint 1 says
    must be loud.
    """


def check(frm: QueueState, to: QueueState, actor: str) -> None:
    """Validate a transition. Raises rather than returning a bool, so it cannot be ignored."""
    if to not in TRANSITIONS.get(frm, set()):
        raise IllegalTransition(f"{frm} -> {to} is not a legal transition")
    if (frm, to) in HUMAN_ONLY and actor != HUMAN:
        raise UnauthorizedActor(
            f"{frm} -> {to} requires a human actor; got {actor!r}. "
            "See CLAUDE.md constraint 1: the tool never submits on its own."
        )
    if to is S.SUBMITTED and actor != HUMAN:
        raise UnauthorizedActor("only a human may mark an application submitted")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def transition(
    conn: sqlite3.Connection,
    entry_id: int,
    to: QueueState,
    *,
    actor: str,
    note: str | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    """Move an entry to a new state, logging who caused it.

    The state_log row is written *before* the UPDATE and inside the same transaction, which is
    what lets the database trigger verify a human authorized a submission.
    """
    row = conn.execute("SELECT state FROM queue_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise LookupError(f"no queue entry {entry_id}")
    frm = QueueState(row["state"])
    check(frm, to, actor)

    ts = now()
    conn.execute(
        "INSERT INTO state_log (queue_entry_id, from_state, to_state, actor, at, note)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (entry_id, frm.value, to.value, actor, ts, note),
    )

    sets = ["state = ?", "state_changed_at = ?"]
    params: list[object] = [to.value, ts]
    for key, value in (extra or {}).items():
        sets.append(f"{key} = ?")
        params.append(value)
    params.append(entry_id)
    conn.execute(f"UPDATE queue_entries SET {', '.join(sets)} WHERE id = ?", params)

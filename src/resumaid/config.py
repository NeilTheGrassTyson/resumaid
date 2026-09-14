"""Paths, settings, and secrets.

Everything the user owns lives under ``~/.resumaid`` — outside the repository, so no amount of
careless ``git add`` can commit a resume. Constraint 4.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR_ENV = "RESUMAID_HOME"

#: Several protections here are POSIX-only. Named once so the reason travels with the check.
IS_WINDOWS = os.name == "nt"


def app_dir() -> Path:
    """The user's data directory. Overridable for tests via ``RESUMAID_HOME``."""
    override = os.environ.get(APP_DIR_ENV)
    return Path(override).expanduser() if override else Path.home() / ".resumaid"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def db(self) -> Path:
        return self.root / "resumaid.db"

    @property
    def resumes(self) -> Path:
        return self.root / "resumes"

    @property
    def writing_samples(self) -> Path:
        # Stage 2 reads these. Created now so the layout is stable; nothing writes here yet.
        return self.root / "writing_samples"

    @property
    def interests(self) -> Path:
        return self.root / "interests.yaml"

    @property
    def profile(self) -> Path:
        return self.root / "profile.yaml"

    @property
    def boards(self) -> Path:
        return self.root / "boards.yaml"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def secrets(self) -> Path:
        return self.root / "secrets.env"

    def ensure(self) -> Paths:
        self.root.mkdir(parents=True, exist_ok=True)
        for d in (self.resumes, self.writing_samples, self.cache):
            d.mkdir(parents=True, exist_ok=True)
        # The data dir holds resumes and PII, so keep it to the owner. POSIX only: on Windows
        # chmod moves the read-only flag and nothing else, so it would imply a protection it
        # does not provide. There, the directory inherits the user profile's ACL, which already
        # restricts it to this account.
        if not IS_WINDOWS:
            os.chmod(self.root, 0o700)
        return self


def paths() -> Paths:
    return Paths(app_dir())


#: Written on `resumaid init` (or `resumaid secrets template`) if secrets.env doesn't exist yet.
#: Every line is commented out — nothing here is a real credential, only where to get one.
SECRETS_TEMPLATE = """\
# API keys for the aggregator sources (DATA_SOURCES.md). Uncomment and fill in whichever you
# register for; a source with no key configured is skipped silently, so this file can stay
# mostly empty. Nothing here is required — Greenhouse, Lever, and Ashby need no key at all.
#
# Without at least one aggregator key, self-registering job boards has nothing to work from:
# add boards yourself on the Setup tab, or via `resumaid board add <url>`.

# Adzuna — broad multi-country listing search. Free tier, ~1,000 calls/month.
# Register at https://developer.adzuna.com/ (a few minutes, no card required) to get an
# app_id and app_key.
# ADZUNA_APP_ID=
# ADZUNA_APP_KEY=

# USAJobs — federal roles. Free, and the one source whose permitted status is not in any doubt.
# Request a key at https://developer.usajobs.gov/APIRequest/Index — it's emailed to the address
# you register with, which USAJOBS_EMAIL below must match (the API requires it on every call).
# USAJOBS_API_KEY=
# USAJOBS_EMAIL=

# Optional, not aggregators — see CLAUDE.md and DATA_SOURCES.md before setting either.
# ANTHROPIC_API_KEY=       # near-the-bar adjudication (ADR 0006)
# PERPLEXITY_API_KEY=      # company research, opt-in, never wired to ingestion
"""


def write_secrets_template(path: Path | None = None, *, overwrite: bool = False) -> Path:
    """Scaffold secrets.env with registration links, never a credential value.

    Mirrors ``write_interests_template`` — a file the user fills in by hand, never touched by
    the app itself. Existing keys are left alone unless ``overwrite`` is set.
    """
    p = path or paths().ensure().secrets
    if p.exists() and not overwrite:
        return p
    p.write_text(SECRETS_TEMPLATE, encoding="utf-8")
    if not IS_WINDOWS:
        os.chmod(p, 0o600)
    return p


def set_secrets(pairs: dict[str, str], path: Path | None = None) -> Path:
    """Write specific key/value pairs into secrets.env, touching nothing else in the file.

    A key already present — live or commented out, as the template ships it — is replaced in
    place; a key with no line yet is appended. Every other line (comments, blanks, keys not in
    ``pairs``) survives untouched, so the registration-link scaffolding stays intact across
    repeated writes. This is the one function that writes an actual credential value to disk —
    everything upstream of it (the API route, the CLI command) exists to reach this and nothing
    more (ADR 0011).
    """
    p = path or paths().ensure().secrets
    if not p.exists():
        write_secrets_template(p)
    remaining = dict(pairs)
    out_lines: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        candidate = stripped[1:].strip() if stripped.startswith("#") else stripped
        key = candidate.split("=", 1)[0].strip() if "=" in candidate else None
        if key in remaining:
            out_lines.append(f"{key}={remaining.pop(key)}")
        else:
            out_lines.append(line)
    out_lines.extend(f"{key}={value}" for key, value in remaining.items())
    p.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    if not IS_WINDOWS:
        os.chmod(p, 0o600)
    return p


def load_secrets(path: Path | None = None) -> dict[str, str]:
    """Read ``KEY=value`` lines from secrets.env, plus anything already in the environment.

    Environment wins, so a shell export can override the file without editing it.
    """
    p = path or paths().secrets
    values: dict[str, str] = {}
    if p.exists():
        # st_mode carries no useful permission bits on Windows — it reports 0o666 for almost
        # every file — so this check would fire on every run with advice (`chmod`) that does
        # not apply there.
        if not IS_WINDOWS and p.stat().st_mode & 0o077:
            # Not fatal — warn loudly rather than block the user's own machine.
            print(f"warning: {p} is readable by others; run  chmod 600 {p}")
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip("\"'")
    for key in (
        "ADZUNA_APP_ID",
        "ADZUNA_APP_KEY",
        "USAJOBS_API_KEY",
        "USAJOBS_EMAIL",
        "ANTHROPIC_API_KEY",
        "PERPLEXITY_API_KEY",
    ):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


@dataclass
class Settings:
    """Runtime knobs. Defaults match REVIEW_QUEUE_SPEC.md."""

    submissions_per_day: int = 5
    surface_multiplier: float = 2.5
    surface_multiplier_bounds: tuple[float, float] = (1.5, 4.0)
    recency_tau_days: float = 21.0
    recency_floor: float = 0.75
    fit_floor: float = 60.0
    # Entries within this many points of the floor get LLM adjudication (ADR 0006).
    adjudication_band: float = 8.0
    max_per_company_per_slate: int = 2
    expire_after_missing_runs: int = 3
    ghost_after_days: int = 30
    approved_reconcile_hours: int = 24
    secrets: dict[str, str] = field(default_factory=load_secrets)

    def secret(self, key: str) -> str | None:
        return self.secrets.get(key)

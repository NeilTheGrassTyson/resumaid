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

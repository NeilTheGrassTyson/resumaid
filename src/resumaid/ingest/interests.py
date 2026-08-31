"""Declared targeting, and profile persistence.

Targeting is runtime input, never repository configuration (CLAUDE.md, Matching and targeting).
Both files live under ~/.resumaid and are hand-editable: the parse is a starting point, not an
authority.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from resumaid.config import paths
from resumaid.models import Interests, Profile

#: Written on `resumaid init`. Structure only — no role family, employer, or industry is a
#: default here, because the tool is profile-agnostic and learns targeting at runtime.
TEMPLATE = """\
# What you're looking for. Edit freely; this file is the source of truth.
#
# role_families: what you want to do, in priority order.
#   weight  — relative importance (higher wins when a role could fit several families).
#   min_fit — an optional higher bar for this family. A family you're lukewarm on stays
#             reachable, but only a genuinely strong match gets queued.
role_families: []
#   - name: example family
#     weight: 1.0
#     keywords: [keyword, another keyword]
#     min_fit: 75

industries: []

locations:
  remote: true
  metros: []
  relocation: "no"      # no | willing | preferred

hard_filters:
  degree_level_min:     # highschool | associate | bachelors | masters | doctorate
  seniority: []         # intern | new-grad | junior | senior
  citizenship_required_ok: true
  clearance_required_ok: false
  employment_types: []

exclusions:
  companies: []
  title_keywords: []

throughput:
  submissions_per_day: 5   # applications you intend to SEND per day. The queue surfaces more
                           # than this, because you reject some of what's queued. The fit bar
                           # never moves to hit the number.
"""


def load_interests(path: Path | None = None) -> Interests:
    p = path or paths().interests
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. Run `resumaid init` to create it."
        )
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Interests.model_validate(data)


def write_interests_template(path: Path | None = None, *, overwrite: bool = False) -> Path:
    p = path or paths().ensure().interests
    if p.exists() and not overwrite:
        return p
    p.write_text(TEMPLATE, encoding="utf-8")
    return p


def save_interests(interests: Interests, path: Path | None = None) -> Path:
    p = path or paths().ensure().interests
    p.write_text(
        yaml.safe_dump(interests.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return p


def load_profile(path: Path | None = None) -> Profile:
    p = path or paths().profile
    if not p.exists():
        raise FileNotFoundError(f"{p} not found. Run `resumaid resume add <file>` first.")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Profile.model_validate(data)


def save_profile(profile: Profile, path: Path | None = None) -> Path:
    """Write the parsed profile for the user to review and correct.

    After the first parse this file is authoritative: re-parsing proposes, the user disposes.
    """
    p = path or paths().ensure().profile
    header = (
        "# Parsed from your resumes, then yours to correct.\n"
        "# This file is the source of truth for matching — re-running the parse will not\n"
        "# overwrite it unless you pass --force.\n"
    )
    body = yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    p.write_text(header + body, encoding="utf-8")
    return p

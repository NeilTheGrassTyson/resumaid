"""Small shared helpers."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")

#: Suffixes stripped when normalizing a company name, so "Acme, Inc." and "Acme" collapse.
_COMPANY_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "plc", "gmbh", "sa", "ag", "bv", "nv", "holdings", "group",
}

#: Noise that varies between listings of the same role.
_TITLE_NOISE = re.compile(
    r"\b(?:remote|hybrid|onsite|on-site|full[- ]time|part[- ]time|contract|intern(?:ship)?"
    r"|us|usa|united states|w2|c2c|urgent|hiring|new)\b",
    re.I,
)
_REQ_ID = re.compile(r"\b(?:req|job|jr|r)[-#_ ]?\d{3,}\b", re.I)
_BRACKETED = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm_company(name: str) -> str:
    """Normalize a company name for duplicate detection."""
    s = _PUNCT.sub(" ", strip_accents(name or "").lower())
    words = [w for w in _WS.sub(" ", s).strip().split(" ") if w and w not in _COMPANY_SUFFIXES]
    return " ".join(words)


def norm_title(title: str) -> str:
    """Normalize a job title for duplicate detection.

    Aggressive on purpose: the duplicate guard's job is to stop re-surfacing a role the user
    already applied to, and a false negative there is far more annoying than a false positive,
    which the user simply un-filters.
    """
    s = strip_accents(title or "").lower()
    s = _BRACKETED.sub(" ", s)
    s = _REQ_ID.sub(" ", s)
    s = s.replace("&", " and ")
    s = re.split(r"\s+[-–—|/]\s+", s)[0]
    s = _TITLE_NOISE.sub(" ", s)
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def dedupe_key(company: str, title: str, locations: list[str] | None = None) -> str:
    loc = ""
    if locations:
        loc = norm_location(locations[0])
    return f"{norm_company(company)}|{norm_title(title)}|{loc}"


def norm_location(loc: str) -> str:
    s = _PUNCT.sub(" ", strip_accents(loc or "").lower())
    return _WS.sub(" ", s).strip()


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def jdump(value: object) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def jload(value: str | None, default: object = None):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def html_to_text(html: str) -> str:
    """Strip tags from an ATS description. Good enough for scoring and display.

    Greenhouse returns its ``content`` field with the markup entity-escaped (``&lt;p&gt;``
    rather than ``<p>``), so unescaping has to happen *before* tags are stripped — otherwise
    the escaped tags survive stripping and land in the text as literal ``<p>``.
    """
    import html as html_mod

    s = html or ""
    if "&lt;" in s or "&gt;" in s:
        s = html_mod.unescape(s)
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()

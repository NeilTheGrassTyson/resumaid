"""The Source protocol, plus rate limiting and an allowlist.

Constraint 3 governs everything here: public ATS JSON APIs and licensed aggregator APIs only.
The allowlist is enforced in code, not merely documented — a request to a host that is not on it
raises rather than being sent.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

import httpx

from resumaid.models import RawPosting

#: Hosts this tool may fetch from. Adding one is a Tier 1 conversation (CLAUDE.md), not an edit.
#:
#: Deliberately absent: any Workday tenant host. Workday's career sites expose an undocumented
#: JSON endpoint their own frontend calls; it is not a published public API and each tenant
#: carries the employer's terms rather than one central policy. CLAUDE.md leaves this an open
#: question, and constraint 3 says a source whose status is unclear is disallowed until checked.
#: Workday roles enter the queue as link-only records instead.
ALLOWED_HOSTS: frozenset[str] = frozenset({
    "boards-api.greenhouse.io",
    "api.lever.co",
    "api.ashbyhq.com",
    "api.adzuna.com",
    "data.usajobs.gov",
})

USER_AGENT = "resumaid/0.1 (personal job-search tool; single user)"


class DisallowedSource(RuntimeError):
    """A request was aimed at a host outside the permitted set."""


def check_host(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise DisallowedSource(
            f"{host!r} is not a permitted source. See CLAUDE.md constraint 3: legitimate data "
            "sourcing only, and a source whose status is unclear is treated as disallowed."
        )


class RateLimiter:
    """A simple token bucket, per host. One user does not need anything cleverer."""

    def __init__(self, per_second: float = 2.0) -> None:
        self._interval = 1.0 / per_second
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            earliest = self._last.get(host, 0.0) + self._interval
            delay = max(0.0, earliest - now)
            self._last[host] = now + delay
        if delay:
            time.sleep(delay)


@dataclass
class FetchContext:
    client: httpx.Client
    limiter: RateLimiter = field(default_factory=RateLimiter)

    def get(self, url: str, **kw) -> httpx.Response:
        check_host(url)
        host = (urlparse(url).hostname or "").lower()
        self.limiter.wait(host)
        headers = {"User-Agent": USER_AGENT, **kw.pop("headers", {})}
        return self.client.get(url, headers=headers, timeout=30.0, **kw)


class Source(Protocol):
    name: str

    def fetch(self, ctx: FetchContext) -> list[RawPosting]:
        ...


def make_client() -> httpx.Client:
    return httpx.Client(follow_redirects=True)

"""Offline place resolution and distance.

Location matching needs to know where places are. A geocoding API is the obvious way to get
that and the wrong one here: this tool is local-first and must work with no network, and
sending the user's home city to a third party for every scored posting is exactly the kind of
leakage constraint 4 exists to prevent.

So coordinates come from a bundled table of the 1,000 most populous US places (~37KB). Postings
name a metro or a state far more often than a street address, so metro resolution covers most of
what arrives; anything it cannot resolve falls back to state matching rather than guessing.

See `docs/adr/0010-offline-place-resolution.md`.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "us_places.csv"

EARTH_RADIUS_MILES = 3958.8

STATE_CODES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "washington dc": "DC", "washington d c": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "puerto rico": "PR",
}

VALID_STATES = set(STATE_CODES.values())

#: Words a posting wraps a location in that carry no geographic meaning.
_NOISE = re.compile(
    r"\b(remote|hybrid|on[- ]?site|onsite|flexible|anywhere|multiple locations|various"
    r"|greater|metro(?:politan)?\s+area|metro|area|region|usa|united states|us|u s)\b",
    re.I,
)
_PUNCT = re.compile(r"[^\w\s,-]")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Place:
    city: str
    state: str
    lat: float
    lon: float
    population: int

    def __str__(self) -> str:
        return f"{self.city}, {self.state}"


@lru_cache(maxsize=1)
def _table() -> tuple[dict[str, list[Place]], list[Place]]:
    """Load the place table once: a city-name index, and the full list."""
    by_city: dict[str, list[Place]] = {}
    every: list[Place] = []
    with DATA.open(encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        for row in rows:
            place = Place(
                city=row["city"],
                state=row["state"],
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                population=int(row["population"]),
            )
            every.append(place)
            by_city.setdefault(_norm(place.city), []).append(place)
    # Most populous first, so an ambiguous bare city name resolves to the one people mean.
    for places in by_city.values():
        places.sort(key=lambda p: -p.population)
    return by_city, every


def _norm(text: str) -> str:
    text = _PUNCT.sub(" ", text or "")
    return _WS.sub(" ", text).strip().lower()


def normalize_state(token: str) -> str | None:
    """Turn 'MA', 'Mass.', or 'Massachusetts' into 'MA'."""
    token = _norm(token).rstrip(".")
    if not token:
        return None
    upper = token.upper()
    if upper in VALID_STATES:
        return upper
    return STATE_CODES.get(token)


def parse_place(text: str) -> tuple[str | None, str | None]:
    """Split a free-text location into (city, state code). Either may be None.

    Handles the shapes postings actually use: "Boston, MA", "Boston, Massachusetts",
    "Greater Boston Area", "Remote - US", "Denver, CO (Hybrid)".
    """
    if not text:
        return None, None
    cleaned = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", text)
    cleaned = _NOISE.sub(" ", cleaned)
    parts = [p.strip() for p in re.split(r"[,/|]|\s+-\s+", cleaned) if p.strip()]
    if not parts:
        return None, None

    state: str | None = None
    for part in reversed(parts):
        state = normalize_state(part)
        if state:
            parts = parts[: parts.index(part)] or []
            break

    city = _norm(parts[0]) if parts else None
    return (city or None), state


def resolve(text: str) -> Place | None:
    """Best-effort place lookup for a free-text location string."""
    city, state = parse_place(text)
    if not city:
        return None
    by_city, _ = _table()
    candidates = by_city.get(city)
    if not candidates:
        return None
    if state:
        for place in candidates:
            if place.state == state:
                return place
        # A city name that exists but not in the named state is a mismatch, not a fallback.
        return None
    return candidates[0]


def state_of(text: str) -> str | None:
    """The state a location string refers to, via an explicit code or a resolved city."""
    _, state = parse_place(text)
    if state:
        return state
    place = resolve(text)
    return place.state if place else None


def distance_miles(a: Place, b: Place) -> float:
    """Great-circle distance. Accurate enough that 'is this commutable' is answerable."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def distance_between(a: str, b: str) -> float | None:
    """Distance between two free-text locations, or None if either cannot be resolved."""
    place_a, place_b = resolve(a), resolve(b)
    if place_a is None or place_b is None:
        return None
    return distance_miles(place_a, place_b)

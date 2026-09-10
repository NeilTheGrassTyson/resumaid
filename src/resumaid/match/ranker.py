"""Ranking: a hard gate upstream, then multiplicative recency and confidence.

    rank_score = fit_score x recency_factor x confidence_factor

    recency_factor = floor + (1 - floor) * exp(-age_days / tau)

Recency is multiplicative and bounded rather than an additive bonus. The factor decays
asymptotically toward the floor instead of being clipped at it, which matters: a clipped
exponential with a short tau reaches its floor within days and then stops distinguishing a
one-week-old posting from a three-month-old one.

The bound is the point. Because the factor never drops below `floor`, recency can overcome a
fit gap of at most 1/floor — with floor 0.75, about 33%. A genuinely stronger role cannot be
buried by a fresher weaker one; comparable roles reorder freely. That is the honest version of
"recency counts, but the fit bar does not move" (ADR 0004).
"""

from __future__ import annotations

import math

from resumaid.config import Settings
from resumaid.models import CONFIDENCE_FACTOR, Confidence, DatePrecision

#: Age assumed when a source gives no usable date. Sources differ badly here — Greenhouse
#: exposes updated_at rather than a true creation date — so this lands mid-range and is
#: flagged in the UI rather than silently treated as fresh.
UNKNOWN_AGE_DAYS = 14.0


def recency_factor(
    age_days: float | None,
    precision: DatePrecision,
    settings: Settings,
) -> tuple[float, str]:
    """Decay by age toward a floor. Returns the factor and the reason to show the user."""
    if age_days is None or precision is DatePrecision.UNKNOWN:
        age = UNKNOWN_AGE_DAYS
        note = "posting date unknown; treated as ~2 weeks old"
    else:
        age = max(0.0, age_days)
        note = f"posted ~{age:.0f}d ago"
        if precision is DatePrecision.APPROXIMATE:
            note += " (approximate)"
    floor = settings.recency_floor
    factor = floor + (1.0 - floor) * math.exp(-age / settings.recency_tau_days)
    return min(1.0, factor), note


def max_overcomable_gap(settings: Settings) -> float:
    """The largest fit ratio recency can invert. Asserted in the tests, not just documented."""
    return 1.0 / settings.recency_floor


def rank_score(
    fit: float,
    age_days: float | None,
    precision: DatePrecision,
    confidence: Confidence,
    settings: Settings,
) -> tuple[float, float, str]:
    rec, note = recency_factor(age_days, precision, settings)
    conf = CONFIDENCE_FACTOR[confidence]
    return fit * rec * conf, rec, note

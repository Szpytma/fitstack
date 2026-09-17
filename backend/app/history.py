"""Fetching the lap detail a structured session needs to be read correctly.

The activity list carries summary fields only, which is all most of FitStack
needs. Plan building is the exception: a threshold read from an interval
session's average is wrong, and an efficiency factor read from one is noise. So
the plan path — and only the plan path — pays for the extra calls.

One provider call per activity, so the candidates are deliberately few: recent
runs long enough to be worth reading, newest first.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.providers.base import FitnessProvider

log = logging.getLogger(__name__)

#: How many activities to fetch laps for. Each is a provider round trip.
DEFAULT_LIMIT = 8
#: Shorter than this says nothing about threshold, structured or not.
MIN_DISTANCE_M = 3000.0
#: Laps from an old session are not evidence about current fitness.
MAX_AGE_DAYS = 56


def _candidates(
    activities: list[dict[str, Any]], today: date, limit: int
) -> list[dict[str, Any]]:
    runs = [
        a
        for a in activities
        if "run" in (a.get("type") or "").lower()
        and (a.get("distance_m") or 0) >= MIN_DISTANCE_M
        and a.get("activity_id")
    ]

    def age(a: dict[str, Any]) -> int:
        try:
            return (today - date.fromisoformat(str(a.get("start_local"))[:10])).days
        except ValueError:
            return MAX_AGE_DAYS + 1

    fresh = [a for a in runs if 0 <= age(a) <= MAX_AGE_DAYS]
    fresh.sort(key=age)
    return fresh[:limit]


def attach_laps(
    provider: FitnessProvider,
    activities: list[dict[str, Any]],
    limit: int = DEFAULT_LIMIT,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Add a `laps` key to the recent runs worth reading in detail.

    Returns the same list. A provider that cannot supply laps, or a single
    activity that fails, leaves the rest untouched — reading a session as steady
    is the old behaviour, not a broken one.
    """
    today = today or date.today()
    for a in _candidates(activities, today, limit):
        try:
            laps = provider.activity_laps(a["activity_id"])
        except NotImplementedError:
            return activities
        except Exception as exc:  # pragma: no cover - upstream flakiness
            log.warning("laps: %s unavailable (%s)", a.get("activity_id"), exc)
            continue
        if laps:
            a["laps"] = laps
    return activities

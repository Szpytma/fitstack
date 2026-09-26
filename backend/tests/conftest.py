"""Fixtures for the planning tests.

Everything under test is pure computation over a list of activity dicts, so the
fixtures are literal dicts in the shape `GarminProvider` returns. No Garmin
account, no network, no recorded cassettes — which is the whole reason this
code is worth testing.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest


def run(
    day: date,
    km: float,
    pace_s_per_km: float = 330.0,
    avg_hr: int | None = 140,
    laps: list[dict[str, Any]] | None = None,
    kind: str = "running",
) -> dict[str, Any]:
    """One activity, in the shape the provider hands the planner."""
    duration_s = km * pace_s_per_km
    return {
        "type": kind,
        "start_local": day.isoformat() + "T07:00:00",
        "distance_m": km * 1000.0,
        "duration_s": duration_s,
        "avg_speed_mps": (km * 1000.0) / duration_s,
        "avg_hr": avg_hr,
        "laps": laps,
    }


def week_of(
    monday: date, weekly_km: float, runs: int = 4, long_share: float = 0.4, **kw: Any
) -> list[dict[str, Any]]:
    """One week totalling `weekly_km`, shaped like a real one.

    The long run matters as much as the total: `weekly_volume` holds the
    starting figure down to what the longest recent run supports, so a week
    split into four equal runs reads as a much smaller athlete than the same
    kilometres with a long run in them.
    """
    long_km = weekly_km * long_share
    rest = (weekly_km - long_km) / max(1, runs - 1)
    out = [run(monday + timedelta(days=6), long_km, **kw)]
    out += [run(monday + timedelta(days=i * 2), rest, **kw) for i in range(runs - 1)]
    return out


def history(
    last_monday: date, weeks: int, weekly_km: float, runs: int = 4, **kw: Any
) -> list[dict[str, Any]]:
    """`weeks` steady weeks, ending with the week starting `last_monday`."""
    out: list[dict[str, Any]] = []
    for w in range(weeks):
        out += week_of(last_monday - timedelta(weeks=w), weekly_km, runs, **kw)
    return out


def laps_steady(n: int = 10, km: float = 1.0, pace_s: float = 330.0) -> list[dict]:
    """An ordinary run: splits wander, nothing alternates.

    The swing is deliberately wide — a recreational runner's kilometres move
    15-20% on hills and road crossings, and that must not read as a session.
    """
    swing = [0.94, 1.06, 0.97, 1.11, 1.02, 0.93, 1.08, 0.99, 1.05, 0.96]
    return [
        {"distance_m": km * 1000.0, "duration_s": pace_s * swing[i % len(swing)]}
        for i in range(n)
    ]


def laps_reps(reps: int = 10, rep_km: float = 1.0) -> list[dict]:
    """10 x 1 km with jog-back recoveries, plus a warmup and a cooldown."""
    out: list[dict[str, Any]] = [{"distance_m": 2000.0, "duration_s": 720.0}]
    for _ in range(reps):
        out.append({"distance_m": rep_km * 1000.0, "duration_s": 240.0})
        out.append({"distance_m": 400.0, "duration_s": 180.0})
    out.append({"distance_m": 1500.0, "duration_s": 540.0})
    return out


def laps_fast_finish(n: int = 10) -> list[dict]:
    """Steady, then one sustained quick block at the end — not reps."""
    out = [{"distance_m": 1000.0, "duration_s": 330.0} for _ in range(n - 3)]
    out += [{"distance_m": 1000.0, "duration_s": 265.0} for _ in range(3)]
    return out


@pytest.fixture
def monday() -> date:
    """A fixed Monday, so nothing in these tests depends on the real calendar."""
    return date(2026, 1, 5)

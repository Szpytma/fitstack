"""Aerobic base training: every run capped in zone 2, progressed by time.

The race planner in `planner.py` builds towards a date — threshold work, VO2
intervals, a taper that lands on race morning. This is the other thing: no race,
no peak, no endpoint. The goal is to run longer at a lower heart rate, which is a
different training problem and needs a different plan.

Three inversions from the race plan, and they are the whole point:

**Heart rate is the input, pace is the output.** `target_mode: "hr"` on a race plan
takes sessions computed from pace and *translates* them to bpm. Here the ceiling is
the prescription: run at 127-147 and whatever pace that produces is the correct
pace today. On a bad day it is slower, and that is the system working.

**Progression is in minutes, not kilometres.** At a fixed heart rate distance is an
outcome. Prescribing kilometres would force the athlete out of the zone to hit them
on a day when the zone is slower — which is exactly the habit this is meant to break.

**Progress is measured by efficiency, not by pace.** The number that should move is
`adapt.efficiency_factor` — metres per minute per heartbeat. Pace rising at constant
heart rate *is* the adaptation; chasing pace directly just puts you back in zone 3.

The output shape deliberately matches `build_plan`, so the rolling-week machinery,
the adaptation rules and the Garmin push all work on it unchanged.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app import adapt
from app.planner import DAYS, assign_days, fmt_duration, fmt_pace

log = logging.getLogger(__name__)

#: Share of the week's minutes that goes to the long run.
LONG_SHARE = 0.35
#: Weekly time growth across the block, before down weeks.
PEAK_MULTIPLE = 1.5
#: Every fourth week backs off to this share.
DOWN_WEEK = 0.75
#: Nobody should start a base block on less than this.
MIN_WEEKLY_MIN = 90.0
#: A single run shorter than this is not worth scheduling.
MIN_RUN_MIN = 25.0
#: Fallback efficiency factor when there is no aerobic history to read one from.
FALLBACK_EF = 0.85


@dataclass
class BaseInput:
    weeks: int = 12
    runs_per_week: int = 4
    long_run_day: str = "Sunday"
    weekly_minutes: float | None = None
    start_date: date | None = None
    plan_name: str | None = None
    #: Allow the long run to drift to the zone 2/3 boundary. Cardiac drift makes
    #: this happen anyway on anything over an hour; pretending otherwise just has
    #: the athlete walking to hold a number.
    long_run_to_boundary: bool = True
    hr_floor: int | None = None
    hr_ceiling: int | None = None
    #: Per-week multipliers from the adaptation rules, keyed by 1-based week.
    week_scale: dict[int, float] | None = None
    warnings: list[str] = field(default_factory=list)


def zone2_band(hr_zones: dict[str, Any] | None) -> tuple[int, int, int] | None:
    """(floor, ceiling, boundary) for zone 2, read from the athlete's own setup.

    The boundary is the zone 3 floor — where "easy" stops being easy. Never
    guessed: an inferred max HR under-reads for anyone training deliberately easy,
    and here the band *is* the prescription.
    """
    floors = (hr_zones or {}).get("zone_floors") or []
    if len(floors) < 3:
        return None
    z2_floor, z3_floor = int(floors[1]), int(floors[2])
    if not 0 < z2_floor < z3_floor:
        return None
    return z2_floor, z3_floor - 1, z3_floor


def observed_weekly_minutes(
    activities: list[dict[str, Any]], weeks: int = 4
) -> float | None:
    """Median weekly running minutes over recent complete weeks.

    Median, not mean: one 3.5-hour week among three quiet ones should not set the
    starting point for a twelve-week block.
    """
    if not activities:
        return None
    today = date.today()
    buckets: dict[int, float] = {}
    for a in activities:
        if "run" not in (a.get("type") or "").lower():
            continue
        try:
            day = date.fromisoformat(str(a.get("start_local") or "")[:10])
        except ValueError:
            continue
        age = (today - day).days
        if not 0 <= age < weeks * 7:
            continue
        buckets[age // 7] = buckets.get(age // 7, 0.0) + float(
            a.get("duration_s") or 0
        ) / 60.0
    if not buckets:
        return None
    filled = [buckets.get(w, 0.0) for w in range(weeks)]
    return round(statistics.median(filled), 1)


def current_ef(activities: list[dict[str, Any]], max_hr: int | None) -> float:
    """Median efficiency factor over recent aerobic runs — the pace predictor.

    Used only to *estimate* what a zone 2 run will cover, so the week has a
    distance to show. The prescription stays time plus heart rate.
    """
    ef, n = adapt.ef_baseline(activities, date.today(), max_hr, weeks=12)
    if ef and n >= 2:
        return ef
    return FALLBACK_EF


def minutes_curve(weeks: int, start_min: float) -> list[tuple[float, bool]]:
    """Weekly minutes with a four-week cycle. → (minutes, is_down)."""
    peak = start_min * PEAK_MULTIPLE
    out: list[tuple[float, bool]] = []
    for i in range(weeks):
        t = i / max(1, weeks - 1)
        mins = start_min + (peak - start_min) * t
        down = (i + 1) % 4 == 0 and i != weeks - 1
        if down:
            mins *= DOWN_WEEK
        out.append((round(mins), down))
    return out


def _steps_hr(duration_s: int, low: int, high: int) -> list[dict[str, Any]]:
    return [
        {
            "kind": "interval",
            "duration_s": int(duration_s),
            "target": {"type": "hr", "low_bpm": int(low), "high_bpm": int(high)},
        }
    ]


def _strides_steps(
    duration_s: int, low: int, high: int, stride_reps: int = 6
) -> list[dict[str, Any]]:
    """Easy running, then short accelerations.

    Strides are 20 seconds with a full minute back to nothing — neuromuscular, not
    aerobic. They leave the zone by design and add no meaningful load, which is why
    they belong in a base block when a threshold session does not.
    """
    body = max(int(duration_s - stride_reps * 80), int(MIN_RUN_MIN * 60))
    return _steps_hr(body, low, high) + [
        {
            "kind": "repeat",
            "iterations": stride_reps,
            "steps": [
                {"kind": "interval", "duration_s": 20},
                {"kind": "recovery", "duration_s": 60},
            ],
        }
    ]


def build_base_plan(
    inp: BaseInput,
    activities: list[dict[str, Any]] | None = None,
    hr_zones: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A zone 2 block: same week/session shape as `build_plan`, different logic."""
    activities = activities or []
    warnings: list[str] = list(inp.warnings)
    today = inp.start_date or date.today()

    band = zone2_band(hr_zones)
    if band:
        z2_low, z2_high, boundary = band
    elif inp.hr_floor and inp.hr_ceiling:
        z2_low, z2_high = int(inp.hr_floor), int(inp.hr_ceiling)
        boundary = z2_high + 1
    else:
        raise ValueError(
            "Zone 2 training needs your configured Garmin heart rate zones — they "
            "are the prescription here, not a detail. Set max HR and zones in "
            "Garmin Connect, or pass an explicit band."
        )

    max_hr = (hr_zones or {}).get("max_hr")
    ef = current_ef(activities, max_hr)

    observed = observed_weekly_minutes(activities)
    start_min = inp.weekly_minutes or observed or MIN_WEEKLY_MIN
    if start_min < MIN_WEEKLY_MIN:
        warnings.append(
            f"Only {start_min:g} min/week of running found recently — starting from "
            f"{MIN_WEEKLY_MIN:g} min instead. Set your current weekly time if that is wrong."
        )
        start_min = MIN_WEEKLY_MIN
    elif observed and not inp.weekly_minutes:
        warnings.append(
            f"Starting from {start_min:g} min/week, the median of your last four weeks."
        )

    runs = max(2, min(7, inp.runs_per_week))
    long_day = DAYS.index(inp.long_run_day) if inp.long_run_day in DAYS else 6
    run_days = assign_days(runs, long_day)

    # Pace at the middle of the band, from the athlete's own efficiency. Shown so
    # the week has a distance on it — the target stays time and heart rate.
    hr_mid = (z2_low + z2_high) / 2.0
    z2_mps = max(0.8, ef * hr_mid / 60.0)
    hr_label = f"{z2_low}–{z2_high} bpm"
    long_high = boundary if inp.long_run_to_boundary else z2_high
    long_label = f"{z2_low}–{long_high} bpm"

    warnings.append(
        f"At {hr_label} expect around {fmt_pace(z2_mps)} — slower than you are used "
        "to. That gap is the point; it closes as the plan works."
    )

    curve = minutes_curve(inp.weeks, start_min)
    if inp.week_scale:
        curve = [
            (round(mins * inp.week_scale.get(i + 1, 1.0)), down)
            for i, (mins, down) in enumerate(curve)
        ]
    first_monday = today + timedelta(days=(7 - today.weekday()) % 7)

    weeks: list[dict[str, Any]] = []
    for i, (week_min, down) in enumerate(curve):
        wk_start = first_monday + timedelta(weeks=i)
        long_min = max(MIN_RUN_MIN, round(week_min * LONG_SHARE))
        others = [d for d in run_days if d != long_day]
        each = max(MIN_RUN_MIN, round((week_min - long_min) / len(others))) if others else 0.0
        # Strides go on the day furthest from the long run.
        stride_day = others[0] if others else None

        sessions: list[dict[str, Any]] = []
        for d in run_days:
            day_date = wk_start + timedelta(days=d)
            is_long = d == long_day
            mins = long_min if is_long else each
            dur_s = int(mins * 60)
            km = round(z2_mps * dur_s / 1000.0, 1)
            low, high = z2_low, (long_high if is_long else z2_high)

            if is_long:
                title = f"Long easy {int(mins)} min"
                note = (
                    "Time on feet at low heart rate. Let it drift to the top of the "
                    "band late on — that is normal, not a reason to push."
                )
                steps = _steps_hr(dur_s, low, high)
                kind = "long"
            elif d == stride_day:
                title = f"Easy {int(mins)} min + strides"
                note = "Easy throughout, then 6 × 20s relaxed accelerations. Form work."
                steps = _strides_steps(dur_s, low, high)
                kind = "quality"
            else:
                title = f"Easy {int(mins)} min"
                note = "If holding the band means walking the hills, walk the hills."
                steps = _steps_hr(dur_s, low, high)
                kind = "easy"

            sessions.append(
                {
                    "date": day_date.isoformat(),
                    "day": DAYS[d],
                    "kind": kind,
                    "title": title,
                    "distance_km": km,
                    "duration_s": dur_s,
                    "pace_label": f"~{fmt_pace(z2_mps)} (whatever the band gives)",
                    "hr_label": f"{low}–{high} bpm",
                    "note": note,
                    "spec": {
                        "name": title[:100],
                        "estimated_duration_s": dur_s,
                        "steps": steps,
                    },
                }
            )

        weeks.append(
            {
                "index": i + 1,
                "start": wk_start.isoformat(),
                "end": (wk_start + timedelta(days=6)).isoformat(),
                "phase": "base",
                "volume_km": round(sum(s["distance_km"] for s in sessions), 1),
                "planned_km": round(z2_mps * week_min * 60 / 1000.0, 1),
                "planned_minutes": round(week_min),
                "down_week": down,
                "sessions": sessions,
            }
        )

    total_km = round(sum(w["volume_km"] for w in weeks), 1)
    peak_km = max((w["planned_km"] for w in weeks), default=0.0)
    last = weeks[-1] if weeks else None

    return {
        "race_name": inp.plan_name or "Aerobic base",
        "race_km": 0.0,
        "race_date": last["end"] if last else today.isoformat(),
        "weeks_total": len(weeks),
        "runs_per_week": runs,
        "long_run_day": inp.long_run_day,
        "peak_week_km": peak_km,
        "total_km": total_km,
        "mode": "base",
        "basis": {
            "source": "recent_activities",
            "threshold_mps": round(z2_mps, 4),
            "threshold_pace": fmt_pace(z2_mps),
            "projected_race_time": None,
            "reference": (
                f"efficiency factor {ef:.2f} at {int(hr_mid)} bpm — "
                f"about {fmt_pace(z2_mps)} in the band today"
            ),
            "weekly_km_observed": None,
            "paces": {
                "easy": hr_label,
                "long": long_label,
                "recovery": f"{z2_low}–{z2_low + 8} bpm",
            },
        },
        "target_mode": "hr",
        "hr_basis": {
            "max_hr": int(max_hr) if max_hr else z2_high * 2,
            "source": "garmin_zones",
            "reference": f"zone 2 is {hr_label}, boundary with zone 3 at {boundary}",
            "resting_hr": (hr_zones or {}).get("resting_hr"),
            "zones": {"easy": hr_label, "long": long_label},
        },
        "warnings": warnings,
        "weeks": weeks,
        "summary": (
            f"{len(weeks)} weeks, {fmt_duration(start_min * 60)} to "
            f"{fmt_duration(curve[-1][0] * 60)} per week, every run at {hr_label}."
        ),
    }

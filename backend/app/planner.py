"""Deterministic race-plan generator.

Pure functions only — no network, no provider, no LLM. Given a race target and
either a goal time or a list of recent activities, this produces a week-by-week
plan whose sessions are already shaped as Garmin workout specs, so the apply
step can upload them without further translation.

Everything here is explainable: paces come from a single threshold speed, which
is derived either from the stated goal time or from the athlete's best recent
effort normalised to a 10K equivalent via Riegel. The basis is reported back so
the UI can show its work.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

# Riegel's endurance exponent: t2 = t1 * (d2/d1) ** 1.06
RIEGEL_EXPONENT = 1.06

DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

Phase = Literal["base", "build", "peak", "taper", "race"]
SessionKind = Literal["long", "quality", "easy", "recovery", "race"]

# Race speed as a multiple of threshold speed (threshold ≈ one-hour race pace).
# Short races are run above threshold, long ones below. Interpolated in log-km.
_RACE_FACTORS: list[tuple[float, float]] = [
    (5.0, 1.06),
    (10.0, 1.02),
    (21.0975, 0.975),
    (42.195, 0.925),
]

# Training speeds, also as multiples of threshold speed: (slow, fast).
_TRAINING_FACTORS: dict[str, tuple[float, float]] = {
    "recovery": (0.66, 0.72),
    "easy": (0.72, 0.80),
    "long": (0.70, 0.78),
    "steady": (0.82, 0.88),
    "threshold": (0.95, 1.00),
    "interval": (1.04, 1.10),
}

# Sane weekly-volume ceilings and long-run caps by race distance (km).
_VOLUME_CEILING: list[tuple[float, float]] = [
    (5.0, 45.0),
    (10.0, 55.0),
    (21.0975, 70.0),
    (42.195, 90.0),
]
_LONG_RUN_CAP: list[tuple[float, float]] = [
    (5.0, 14.0),
    (10.0, 18.0),
    (21.0975, 24.0),
    (42.195, 32.0),
]
#: Time ceiling on the long run, in minutes. Distance alone is the wrong unit for
#: this cap: 32 km is a three-hour run for one athlete and a four-and-a-half hour
#: one for another, and past about three hours the cost climbs faster than the
#: adaptation. Whichever cap binds first wins.
_LONG_RUN_MAX_MIN: list[tuple[float, float]] = [
    (5.0, 75.0),
    (10.0, 90.0),
    (21.0975, 135.0),
    (42.195, 180.0),
]

#: No single run may take more than this share of its week. The share-of-week
#: rule drives the long run in an ordinary block; this is the backstop for when
#: the absolute ramp would otherwise let one run swallow the week.
MAX_LONG_SHARE = 0.40


def _interp(table: list[tuple[float, float]], km: float) -> float:
    """Linear interpolation over log-distance, clamped at both ends."""
    import math

    if km <= table[0][0]:
        return table[0][1]
    if km >= table[-1][0]:
        return table[-1][1]
    for (d0, v0), (d1, v1) in zip(table, table[1:]):
        if d0 <= km <= d1:
            t = (math.log(km) - math.log(d0)) / (math.log(d1) - math.log(d0))
            return v0 + (v1 - v0) * t
    return table[-1][1]


def race_speed_factor(km: float) -> float:
    return _interp(_RACE_FACTORS, km)


def fmt_pace(mps: float | None) -> str:
    """m/s → 'm:ss/km'."""
    if not mps or mps <= 0:
        return "—"
    secs = 1000.0 / mps
    return f"{int(secs // 60)}:{int(round(secs % 60)):02d}/km"


def fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def riegel(time_s: float, from_km: float, to_km: float) -> float:
    """Project a race time from one distance to another."""
    if from_km <= 0:
        return 0.0
    return time_s * (to_km / from_km) ** RIEGEL_EXPONENT


# --------------------------------------------------------------------------
# fitness basis
# --------------------------------------------------------------------------


@dataclass
class Basis:
    """How the paces were arrived at — surfaced to the user verbatim."""

    source: Literal["goal_time", "recent_activities", "stated_volume"]
    threshold_mps: float
    projected_race_time: str | None = None
    reference: str | None = None
    reference_activity_id: int | None = None
    weekly_km_observed: float | None = None
    paces: dict[str, str] = field(default_factory=dict)


def _running(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for a in activities:
        t = (a.get("type") or "").lower()
        if "run" not in t:
            continue
        d, s = a.get("distance_m"), a.get("duration_s")
        if not d or not s or d < 3000 or s <= 0:
            continue
        out.append(a)
    return out


def threshold_from_activities(
    activities: list[dict[str, Any]],
) -> tuple[float | None, dict[str, Any] | None]:
    """Best recent effort, normalised to a 10K equivalent → threshold speed.

    Every qualifying run is projected to a 10K time with Riegel; the fastest
    projection wins. This rewards a strong short effort and a strong long one
    alike, rather than assuming the longest run is the best indicator.
    """
    runs = _running(activities)
    if not runs:
        return None, None

    best_t10k: float | None = None
    best: dict[str, Any] | None = None
    for a in runs:
        km = float(a["distance_m"]) / 1000.0
        t10k = riegel(float(a["duration_s"]), km, 10.0)
        if best_t10k is None or t10k < best_t10k:
            best_t10k, best = t10k, a

    if best_t10k is None or best_t10k <= 0:
        return None, None

    v10k = 10000.0 / best_t10k
    return v10k / race_speed_factor(10.0), best


def threshold_from_goal(goal_time_s: float, race_km: float) -> float:
    v_race = (race_km * 1000.0) / goal_time_s
    return v_race / race_speed_factor(race_km)


def observed_weekly_km(activities: list[dict[str, Any]], weeks: int = 4) -> float | None:
    """Average weekly running volume over the last `weeks` weeks of data."""
    runs = _running(activities)
    if not runs:
        return None
    cutoff = date.today() - timedelta(weeks=weeks)
    total = 0.0
    seen = False
    for a in runs:
        start = (a.get("start_local") or "")[:10]
        try:
            day = date.fromisoformat(start)
        except ValueError:
            continue
        if day >= cutoff:
            total += float(a["distance_m"]) / 1000.0
            seen = True
    return round(total / weeks, 1) if seen else None


def pace_range(threshold_mps: float, key: str) -> tuple[float, float]:
    lo, hi = _TRAINING_FACTORS[key]
    return threshold_mps * lo, threshold_mps * hi


def pace_label(threshold_mps: float, key: str) -> str:
    lo, hi = pace_range(threshold_mps, key)
    return f"{fmt_pace(hi)}–{fmt_pace(lo)}"


# --------------------------------------------------------------------------
# volume + phase model
# --------------------------------------------------------------------------


def taper_weeks_for(race_km: float) -> int:
    return 3 if race_km >= 30 else 2


def phase_for(week_idx: int, total: int, taper: int) -> Phase:
    """week_idx is 0-based; the final week is race week."""
    if week_idx == total - 1:
        return "race"
    if week_idx >= total - taper:
        return "taper"
    build_len = total - taper
    if week_idx < build_len * 0.4:
        return "base"
    if week_idx < build_len * 0.75:
        return "build"
    return "peak"


def volume_curve(
    total_weeks: int, start_km: float, peak_km: float, taper: int
) -> list[tuple[float, bool]]:
    """Weekly volume with a 4-week down-week cycle and a taper. → (km, is_down)."""
    build_len = max(1, total_weeks - taper)
    out: list[tuple[float, bool]] = []

    for i in range(build_len):
        t = i / max(1, build_len - 1)
        vol = start_km + (peak_km - start_km) * t
        down = (i + 1) % 4 == 0 and i != build_len - 1
        if down:
            vol *= 0.75
        out.append((round(vol, 1), down))

    # Taper: step down from the last build week, race week lightest.
    last = out[-1][0] if out else start_km
    ramp = [0.75, 0.55, 0.40][-taper:] if taper <= 3 else [0.75, 0.55, 0.40]
    for f in ramp[:taper]:
        out.append((round(last * f, 1), False))

    return out[:total_weeks]


def peak_volume(start_km: float, race_km: float, build_weeks: int = 12) -> float:
    """Where weekly volume tops out — the lift scales with how long the build is.

    A flat 60% lift is right for a twelve-week build and far too timid for a
    twenty-four week one: the same ramp given twice the time to do it in. On a
    marathon block it is also what kept the long run short enough to make the
    whole plan a half-marathon plan in disguise, because the long run is a share
    of the week and the week never grew. Roughly 5% of the starting volume per
    build week, clamped at 2.2x — and the distance ceiling still applies.
    """
    ceiling = _interp(_VOLUME_CEILING, race_km)
    lift = max(1.1, min(1.0 + 0.05 * build_weeks, 2.2))
    return round(max(start_km * 1.1, min(start_km * lift, ceiling)), 1)


def long_run_cap(race_km: float, long_mps: float | None = None) -> float:
    """The longest single run this block will ever prescribe.

    Distance cap and time cap, whichever binds first. Without a pace the time cap
    cannot be applied and the distance one stands alone, which is the old
    behaviour and why `long_mps` is optional.

    Note the distance cap is *not* tied to race distance: 5K runners should train
    well beyond 5 km, while the marathon cap sits far below 42 km by design.
    """
    cap = _interp(_LONG_RUN_CAP, race_km)
    if long_mps and long_mps > 0:
        cap = min(cap, long_mps * _interp(_LONG_RUN_MAX_MIN, race_km) * 60.0 / 1000.0)
    return round(cap, 1)


def long_run_km(
    weekly_km: float, race_km: float, phase: Phase, long_mps: float | None = None
) -> float:
    """The share-of-week rule: what this week's volume alone implies.

    This is the floor the absolute ramp in `long_run_curve` builds on, and it is
    the whole rule during the taper, where the long run should shrink with the
    week rather than keep climbing.
    """
    cap = long_run_cap(race_km, long_mps)
    share = 0.30 if phase in ("base", "build") else 0.33
    if phase in ("taper", "race"):
        share = 0.25
    # Floor so a low-volume week still produces a run worth calling "long" —
    # but never let it swallow the week: 35% is the ceiling on the floor.
    floor = min(6.0 if race_km <= 10 else 8.0, cap, weekly_km * 0.35)
    return round(min(max(weekly_km * share, floor), cap), 1)


def longest_recent_run_km(
    activities: list[dict[str, Any]], before: date, days: int = 30
) -> float | None:
    """The longest single run in the `days` before `before`, in km."""
    best = 0.0
    for a in _running(activities):
        try:
            day = date.fromisoformat(str(a.get("start_local") or "")[:10])
        except ValueError:
            continue
        if 0 <= (before - day).days < days:
            best = max(best, float(a["distance_m"]) / 1000.0)
    return round(best, 1) or None


def progression_ceilings(
    lr_curve: list[float],
    longest_recent: float | None,
    step: float = 1.10,
    hard_cap: float | None = None,
) -> list[float]:
    """The furthest each long run may go, given the ones behind it.

    A cohort of 5200+ runners found materially higher overuse-injury risk when a
    single run passed 110% of the longest run in the previous 30 days — whether or
    not weekly volume moved. The block's own ramp is gentler than that after the
    first few weeks, so this binds at the start, where the plan meets an athlete
    who has not been running the distances it assumes.

    Walks forward: each week may exceed the best of (what history shows, what the
    plan has already asked for) by `step`. Returned as ceilings rather than
    applied, because the week assembly has to respect them too — the spill rule
    used to push the long run straight back past this guard.
    """
    fallback = hard_cap if hard_cap is not None else float("inf")
    if not longest_recent:
        return [fallback] * len(lr_curve)
    out: list[float] = []
    reached = longest_recent
    for km in lr_curve:
        allowed = round(reached * step, 1)
        if hard_cap is not None:
            allowed = min(allowed, hard_cap)
        out.append(allowed)
        reached = max(reached, min(km, allowed))
    return out


def long_run_curve(
    curve: list[tuple[float, bool]],
    race_km: float,
    total_weeks: int,
    taper: int,
    long_mps: float | None = None,
) -> list[float]:
    """Week-by-week long run — an absolute progression, not just a share.

    The share rule on its own bounds the long run by the *starting* volume: at
    30% of a week that tops out at 48 km, a marathon block peaks at a 16 km long
    run, which prepares nobody for 42 km. So the long run gets a ramp of its own,
    from what the first week implies up to `long_run_cap`, with the share rule
    kept as a floor and `MAX_LONG_SHARE` as the ceiling on any single run.

    Down weeks pull the long run back with the rest of the week, and the taper is
    left entirely to the share rule — a long run that kept climbing into race
    week would defeat the taper.

    Pure function of the volume curve, so a rolling plan replays identically.
    """
    cap = long_run_cap(race_km, long_mps)
    build_len = max(1, total_weeks - taper)
    first = long_run_km(curve[0][0], race_km, "base", long_mps) if curve else 0.0

    out: list[float] = []
    for i, (vol, down) in enumerate(curve):
        phase = phase_for(i, total_weeks, taper)
        share_km = long_run_km(vol, race_km, phase, long_mps)
        if phase in ("taper", "race"):
            out.append(share_km)
            continue
        t = i / max(1, build_len - 1)
        target = first + (cap - first) * t
        if down:
            target *= 0.8
        km = min(max(share_km, target), cap, vol * MAX_LONG_SHARE)
        out.append(round(km, 1))
    return out


# --------------------------------------------------------------------------
# session layout
# --------------------------------------------------------------------------


def assign_days(runs_per_week: int, long_day: int) -> list[int]:
    """Spread `runs_per_week` sessions over the week, long run on `long_day`.

    Greedy and deterministic: repeatedly take the day furthest (cyclically) from
    everything already chosen, so hard days do not end up adjacent.
    """
    chosen = [long_day]
    while len(chosen) < min(runs_per_week, 7):
        best_day, best_gap = None, -1
        for d in range(7):
            if d in chosen:
                continue
            gap = min(min((d - c) % 7, (c - d) % 7) for c in chosen)
            if gap > best_gap:
                best_day, best_gap = d, gap
        chosen.append(best_day if best_day is not None else 0)
    return sorted(chosen)


def steps_distance_km(steps: list[dict[str, Any]], default_mps: float) -> float:
    """Distance implied by a step tree, so distance and duration never disagree.

    Each leaf contributes duration × its own target speed; untargeted steps fall
    back to `default_mps` (easy running).
    """
    total_m = 0.0
    for s in steps:
        if s.get("kind") == "repeat":
            inner = steps_distance_km(s.get("steps") or [], default_mps) * 1000.0
            total_m += inner * int(s.get("iterations") or 1)
            continue
        dur = float(s.get("duration_s") or 0)
        target = s.get("target") or {}
        if target.get("type") == "pace":
            speed = (float(target["low_mps"]) + float(target["high_mps"])) / 2.0
        else:
            speed = default_mps
        total_m += dur * speed
    return total_m / 1000.0


# Intensity bands as a fraction of max HR, keyed by how the step's pace target
# compares with threshold speed. Percentages follow the usual 5-zone model.
#
# The ratio cut-points are calibrated against the pace bands this planner itself
# emits, not guessed: recovery lands near 0.69 of threshold speed, long 0.74,
# easy 0.76, threshold and race 0.98, intervals 1.07. Cuts sit in the gaps.
# Get these wrong and every aerobic session collapses into one band.
_HR_BANDS: list[tuple[float, float, float, str]] = [
    # (max speed ratio vs threshold, %HRmax low, %HRmax high, label)
    (0.72, 0.60, 0.70, "recovery"),
    (0.80, 0.65, 0.75, "easy"),
    (0.90, 0.70, 0.80, "steady"),
    (1.02, 0.82, 0.88, "threshold"),
    (99.0, 0.90, 0.96, "interval"),
]


def estimate_max_hr(activities: list[dict[str, Any]]) -> tuple[int | None, str | None]:
    """Peak HR seen across recent runs, plus the run it came from.

    Uses the median of the three highest rather than the single highest: one
    strap artifact reading 210 would otherwise set every band in the plan. With
    a genuine cluster of hard efforts the two agree within a beat or two.

    Training rarely reaches true max, so this still under-reads — the bands
    built on it are correspondingly conservative, which is the safe direction.
    """
    samples: list[tuple[float, str | None]] = []
    for a in activities:
        if "run" not in (a.get("type") or "").lower():
            continue
        hr = a.get("max_hr")
        if hr is None:
            continue
        try:
            hr = float(hr)
        except (TypeError, ValueError):
            continue
        if not 120.0 <= hr <= 220.0:  # stray sensor values
            continue
        samples.append((hr, a.get("name") or a.get("start_local")))

    if not samples:
        return None, None

    samples.sort(key=lambda s: s[0], reverse=True)
    top = samples[:3]
    estimate = statistics.median([hr for hr, _ in top])
    # Attribute to whichever run actually sits at the estimate.
    ref = min(top, key=lambda s: abs(s[0] - estimate))[1]
    return int(round(estimate)), ref


def bands_from_zone_floors(
    zone_floors: list[int], max_hr: int
) -> list[tuple[float, int, int, str]]:
    """Turn Garmin's five zone floors into (ratio cut, low bpm, high bpm, label).

    Each zone runs from its own floor to the next one up; zone 5 tops out at max
    HR. Using the athlete's configured ladder means the plan and the watch agree
    on what "zone 4" means, instead of the plan inventing its own percentages.
    """
    edges = list(zone_floors) + [max_hr]
    labels = ["recovery", "easy", "steady", "threshold", "interval"]
    cuts = [c for c, _lo, _hi, _l in _HR_BANDS]
    return [
        (cuts[i], int(edges[i]), int(edges[i + 1]), labels[i])
        for i in range(5)
    ]


def hr_band_for_speed(
    low_mps: float,
    high_mps: float,
    threshold_mps: float,
    max_hr: int,
    bands: list[tuple[float, int, int, str]] | None = None,
) -> tuple[int, int, str]:
    """Map a pace target onto a bpm range via its intensity relative to threshold."""
    mid = (low_mps + high_mps) / 2.0
    ratio = mid / threshold_mps if threshold_mps else 1.0
    if bands is not None:
        for cut, lo, hi, label in bands:
            if ratio < cut:
                return lo, hi, label
        last = bands[-1]
        return last[1], last[2], last[3]
    for cut, lo_pct, hi_pct, label in _HR_BANDS:
        if ratio < cut:
            return int(round(max_hr * lo_pct)), int(round(max_hr * hi_pct)), label
    return int(round(max_hr * 0.90)), int(round(max_hr * 0.96)), "interval"


def convert_targets_to_hr(
    steps: list[dict[str, Any]],
    threshold_mps: float,
    max_hr: int,
    bands: list[tuple[float, int, int, str]] | None = None,
) -> list[dict[str, Any]]:
    """Rewrite every pace target in a step tree as a heart-rate target.

    Runs after the plan is built so distance and duration stay derived from
    pace — only what the watch is told to chase changes.
    """
    out: list[dict[str, Any]] = []
    for s in steps:
        step = dict(s)
        if step.get("kind") == "repeat":
            step["steps"] = convert_targets_to_hr(
                step.get("steps") or [], threshold_mps, max_hr, bands
            )
            out.append(step)
            continue
        target = step.get("target") or {}
        if target.get("type") == "pace":
            lo, hi, _label = hr_band_for_speed(
                float(target["low_mps"]),
                float(target["high_mps"]),
                threshold_mps,
                max_hr,
                bands,
            )
            step["target"] = {"type": "hr", "low_bpm": lo, "high_bpm": hi}
        out.append(step)
    return out


def hr_label_for_steps(steps: list[dict[str, Any]]) -> str | None:
    """The bpm range a session is actually run at.

    Takes the longest HR-targeted leaf, so an interval session is described by
    its work bouts rather than by a warmup that happens to come first.
    """
    best: tuple[float, dict[str, Any]] | None = None

    def walk(items: list[dict[str, Any]], mult: int = 1) -> None:
        nonlocal best
        for s in items:
            if s.get("kind") == "repeat":
                walk(s.get("steps") or [], mult * int(s.get("iterations") or 1))
                continue
            t = s.get("target") or {}
            if t.get("type") != "hr":
                continue
            weight = float(s.get("duration_s") or 0) * mult
            if best is None or weight > best[0]:
                best = (weight, t)

    walk(steps)
    if best is None:
        return None
    return f"{best[1]['low_bpm']}–{best[1]['high_bpm']} bpm"


def _steps_steady(duration_s: int, lo: float, hi: float) -> list[dict[str, Any]]:
    return [
        {
            "kind": "interval",
            "duration_s": duration_s,
            "target": {"type": "pace", "low_mps": round(lo, 3), "high_mps": round(hi, 3)},
        }
    ]


def _steps_intervals(
    reps: int,
    work_s: int,
    rest_s: int,
    work: tuple[float, float],
    easy: tuple[float, float],
    warmup_s: int = 900,
    cooldown_s: int = 600,
) -> list[dict[str, Any]]:
    return [
        {"kind": "warmup", "duration_s": warmup_s},
        {
            "kind": "repeat",
            "iterations": reps,
            "steps": [
                {
                    "kind": "interval",
                    "duration_s": work_s,
                    "target": {
                        "type": "pace",
                        "low_mps": round(work[0], 3),
                        "high_mps": round(work[1], 3),
                    },
                },
                {"kind": "recovery", "duration_s": rest_s},
            ],
        },
        {"kind": "cooldown", "duration_s": cooldown_s},
    ]


def _clamp(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(v))))


def quality_session(
    phase: Phase, threshold_mps: float, race_km: float, weekly_km: float
) -> tuple[str, list[dict[str, Any]], int, float, str, str]:
    """→ (title, steps, duration_s, distance_km, note, pace_label) for the week.

    The label describes what the session mostly *is*, so it matches the work.
    Base-phase strides are easy running with 20-second accelerations in it —
    labelling that with threshold pace reads as a hard session and invites exactly
    the grey-zone running these plans are meant to avoid.

    Rep counts scale with weekly volume — a 25 km/week runner should not be handed
    the same threshold session as someone on 70.
    """
    easy = pace_range(threshold_mps, "easy")
    thr = pace_range(threshold_mps, "threshold")
    itv = pace_range(threshold_mps, "interval")
    easy_mid = (easy[0] + easy[1]) / 2.0
    race_v = threshold_mps * race_speed_factor(race_km)
    race_target = (race_v * 0.985, race_v * 1.015)

    # Warmup/cooldown shrink for lower-volume athletes.
    wu = 900 if weekly_km >= 40 else 600
    cd = 600 if weekly_km >= 40 else 480

    def finish(title: str, steps: list[dict[str, Any]], note: str, pace_key: str):
        # "race" has no entry in _TRAINING_FACTORS — it is derived from the race
        # distance, not a fixed multiple of threshold — so label it here.
        label = (
            f"{fmt_pace(race_target[1])}–{fmt_pace(race_target[0])}"
            if pace_key == "race"
            else pace_label(threshold_mps, pace_key)
        )
        dur = 0.0
        for s in steps:
            if s.get("kind") == "repeat":
                dur += sum(
                    float(i.get("duration_s") or 0) for i in (s.get("steps") or [])
                ) * int(s.get("iterations") or 1)
            else:
                dur += float(s.get("duration_s") or 0)
        return (
            title,
            steps,
            int(dur),
            round(steps_distance_km(steps, easy_mid), 1),
            note,
            label,
        )

    if phase == "base":
        # Easy volume with strides — neuromuscular work without the load.
        target_km = min(max(weekly_km * 0.22, 4.0), weekly_km * 0.30, 10.0)
        dur = int(target_km / easy_mid * 1000)
        steps = _steps_steady(dur, *easy) + [
            {
                "kind": "repeat",
                "iterations": 6,
                "steps": [
                    {
                        "kind": "interval",
                        "duration_s": 20,
                        "target": {
                            "type": "pace",
                            "low_mps": round(itv[0], 3),
                            "high_mps": round(itv[1], 3),
                        },
                    },
                    {"kind": "recovery", "duration_s": 60},
                ],
            }
        ]
        return finish(
            "Easy + strides",
            steps,
            "Relaxed running, then 6 × 20s strides — form work, not a workout.",
            "easy",
        )

    if phase == "build":
        reps = _clamp(weekly_km / 12.0, 3, 5)
        work_s, rest_s = 480, 120
        return finish(
            f"Threshold {reps}×8min",
            _steps_intervals(reps, work_s, rest_s, thr, easy, wu, cd),
            "Comfortably hard — you could speak a sentence, not hold a conversation.",
            "threshold",
        )

    if phase == "peak":
        if race_km >= 21:
            reps = _clamp(weekly_km / 18.0, 3, 5)
            work_s, rest_s, target = 900, 180, race_target
            title = f"Race pace {reps}×15min"
            key = "race"
        else:
            reps = _clamp(weekly_km / 8.0, 4, 8)
            work_s, rest_s, target = 180, 120, itv
            title = f"VO2 {reps}×3min"
            key = "interval"
        return finish(
            title,
            _steps_intervals(reps, work_s, rest_s, target, easy, wu, cd),
            "The specific session — this is the one that makes race day feel familiar.",
            key,
        )

    # taper / race week
    reps, work_s, rest_s = 4, 120, 120
    return finish(
        f"Sharpener {reps}×2min",
        _steps_intervals(reps, work_s, rest_s, race_target, easy, wu, cd),
        "Short and snappy. The fitness is banked — this just keeps the legs awake.",
        "race",
    )


# --------------------------------------------------------------------------
# plan assembly
# --------------------------------------------------------------------------


@dataclass
class PlanInput:
    race_km: float
    race_date: date
    runs_per_week: int = 4
    long_run_day: str = "Sunday"
    weekly_km: float | None = None
    goal_time_s: float | None = None
    race_name: str | None = None
    start_date: date | None = None
    target_mode: str = "pace"  # "pace" | "hr"
    # Per-week volume multipliers, keyed by 1-based week number. Set by the
    # rolling planner when a week is held back; applied to the volume curve
    # *before* sessions are shaped, so long-run caps and spill still hold.
    week_scale: dict[int, float] | None = None


def _session(
    day: date,
    kind: SessionKind,
    title: str,
    distance_km: float,
    duration_s: int,
    steps: list[dict[str, Any]],
    pace: str,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "date": day.isoformat(),
        "day": DAYS[day.weekday()],
        "kind": kind,
        "title": title,
        "distance_km": round(distance_km, 1),
        "duration_s": int(duration_s),
        "pace_label": pace,
        "note": note,
        # Race day carries no workout — nothing to upload or schedule.
        "spec": (
            {
                "name": title[:100],
                "estimated_duration_s": int(duration_s),
                "steps": steps,
            }
            if steps
            else None
        ),
    }


#: The longest block `build_plan` will lay out. A race further away than this is
#: not planned in full: the weeks before the block are lead-in, and belong to the
#: aerobic base planner (see `active_plan.lead_in_view`).
MAX_BLOCK_WEEKS = 24


def block_weeks(start_date: date, race_date: date) -> int:
    """How many weeks the race block itself covers."""
    return max(4, min(MAX_BLOCK_WEEKS, (race_date - start_date).days // 7))


def block_start(start_date: date, race_date: date) -> date:
    """The Monday the race block opens on.

    Weeks are anchored *backwards* from race week, so a block shorter than the
    runway starts later than today — that gap is the lead-in, not an error.
    """
    race_week_start = race_date - timedelta(days=race_date.weekday())
    return race_week_start - timedelta(weeks=block_weeks(start_date, race_date) - 1)


def build_plan(
    inp: PlanInput,
    activities: list[dict[str, Any]] | None = None,
    hr_zones: dict[str, Any] | None = None,
) -> dict[str, Any]:
    activities = activities or []
    today = inp.start_date or date.today()
    warnings: list[str] = []

    days_out = (inp.race_date - today).days
    if days_out < 7:
        raise ValueError("Race date must be at least a week away to build a plan.")
    total_weeks = block_weeks(today, inp.race_date)
    if days_out // 7 > MAX_BLOCK_WEEKS:
        opens = block_start(today, inp.race_date)
        warnings.append(
            f"Race is {days_out // 7} weeks out — this block is the final "
            f"{MAX_BLOCK_WEEKS} weeks and opens on {opens.isoformat()}. The weeks "
            "before it are lead-in: build aerobic base there."
        )

    # --- fitness basis -----------------------------------------------------
    ref_activity: dict[str, Any] | None = None
    if inp.goal_time_s:
        threshold = threshold_from_goal(inp.goal_time_s, inp.race_km)
        source: Any = "goal_time"
    else:
        threshold, ref_activity = threshold_from_activities(activities)
        source = "recent_activities"
        if threshold is None:
            raise ValueError(
                "No goal time given and no recent runs over 3 km to estimate fitness "
                "from. Enter a goal time, or sync some runs first."
            )

    observed = observed_weekly_km(activities)
    stated = inp.weekly_km if inp.weekly_km else None
    start_km = stated or observed or max(15.0, inp.race_km * 0.8)
    # A plan cannot start below what its own session structure implies.
    floor = max(inp.runs_per_week * 4.0, 12.0)
    if start_km < floor:
        if stated:
            warnings.append(
                f"{start_km:g} km/week over {inp.runs_per_week} runs is very light — "
                f"the plan starts nearer {floor:g} km so the sessions are worth doing."
            )
        else:
            warnings.append(
                f"Only {start_km:g} km/week found in recent activities — starting from "
                f"{floor:g} km instead. Set your current weekly km if that is wrong."
            )
        start_km = floor
    if stated is None and observed is None:
        warnings.append(
            "No recent volume found — assumed a modest starting week. Set your current "
            "weekly km for a plan that fits where you actually are."
        )
    # A stated volume is taken at face value, but it is worth saying out loud when
    # it is far ahead of what the athlete has actually been running: the plan then
    # opens with a jump no ramp inside it can undo.
    if stated and observed is not None and stated > observed * 1.5:
        warnings.append(
            f"You entered {stated:g} km/week but recent activities show about "
            f"{observed:g} km/week. The plan is built on {stated:g} km, so week 1 asks "
            f"for roughly {stated / max(observed, 0.1):.0f}x your current volume — "
            "lower it if that is not deliberate."
        )

    # Sanity-check the goal against observed fitness.
    if inp.goal_time_s and activities:
        est, _ = threshold_from_activities(activities)
        if est and threshold > est * 1.08:
            warnings.append(
                "That goal time is well ahead of what your recent runs suggest — the "
                "paces below will feel harder than the labels imply."
            )

    projected = riegel(
        10000.0 / (threshold * race_speed_factor(10.0)), 10.0, inp.race_km
    )

    basis = Basis(
        source=source,
        threshold_mps=round(threshold, 4),
        projected_race_time=fmt_duration(projected),
        weekly_km_observed=observed,
        paces={
            "recovery": pace_label(threshold, "recovery"),
            "easy": pace_label(threshold, "easy"),
            "long": pace_label(threshold, "long"),
            "threshold": pace_label(threshold, "threshold"),
            "interval": pace_label(threshold, "interval"),
            "race": fmt_pace(threshold * race_speed_factor(inp.race_km)),
        },
    )
    if ref_activity:
        basis.reference = (
            f"{ref_activity.get('name') or 'run'} — "
            f"{float(ref_activity['distance_m']) / 1000:.1f} km in "
            f"{fmt_duration(float(ref_activity['duration_s']))}"
        )
        basis.reference_activity_id = ref_activity.get("activity_id")

    # --- volume ------------------------------------------------------------
    taper = taper_weeks_for(inp.race_km)
    peak = peak_volume(start_km, inp.race_km, total_weeks - taper)
    curve = volume_curve(total_weeks, start_km, peak, taper)
    if inp.week_scale:
        curve = [
            (round(vol * inp.week_scale.get(i + 1, 1.0), 1), down)
            for i, (vol, down) in enumerate(curve)
        ]

    long_day = DAYS.index(inp.long_run_day) if inp.long_run_day in DAYS else 6
    run_days = assign_days(max(2, min(7, inp.runs_per_week)), long_day)

    easy_p = pace_range(threshold, "easy")
    long_p = pace_range(threshold, "long")
    rec_p = pace_range(threshold, "recovery")

    # The long run progresses on its own terms; see `long_run_curve`. Built from
    # the already-scaled curve so an adaptation hold pulls it back too.
    long_mid = (long_p[0] + long_p[1]) / 2.0
    lr_cap = long_run_cap(inp.race_km, long_mid)
    lr_curve = long_run_curve(curve, inp.race_km, total_weeks, taper, long_mid)
    longest_recent = longest_recent_run_km(activities, today)
    lr_ceilings = progression_ceilings(lr_curve, longest_recent, hard_cap=lr_cap)
    clamped = [min(km, c) for km, c in zip(lr_curve, lr_ceilings)]
    if clamped != lr_curve:
        first_held = next(
            (i for i, (a, b) in enumerate(zip(clamped, lr_curve)) if a < b), 0
        )
        warnings.append(
            f"Your longest run in the last 30 days is {longest_recent:g} km, so the "
            f"first long runs are held to about 10% above it (week {first_held + 1} "
            f"asks {clamped[first_held]:g} km, not {lr_curve[first_held]:g} km). "
            "The long run climbs from there."
        )
    lr_curve = clamped

    # Race week ends on race day; walk backwards from there.
    race_week_start = inp.race_date - timedelta(days=inp.race_date.weekday())
    first_week_start = race_week_start - timedelta(weeks=total_weeks - 1)

    weeks: list[dict[str, Any]] = []
    for i, (vol, down) in enumerate(curve):
        phase = phase_for(i, total_weeks, taper)
        wk_start = first_week_start + timedelta(weeks=i)
        sessions: list[dict[str, Any]] = []

        lr_km = lr_curve[i]
        q_title, q_steps, q_dur, q_km, q_note, q_pace_label = quality_session(
            phase, threshold, inp.race_km, vol
        )
        remaining = max(0.0, vol - lr_km - q_km)
        easy_days = [d for d in run_days if d != long_day]
        # The quality session takes the day furthest from the long run.
        q_day = easy_days[0] if easy_days else long_day
        filler_days = [d for d in easy_days if d != q_day]
        per_filler = round(remaining / len(filler_days), 1) if filler_days else 0.0

        # An easy day must never out-distance the long run — on low run-count
        # weeks the remainder would otherwise pile onto a single midweek run.
        #
        # Two things this must not do. It must not push the long run past the
        # progression ceiling: that guard exists precisely for the weeks where the
        # week's volume outruns what the athlete's longest run supports, which is
        # exactly when this branch fires. And it must not run in the taper, where
        # evenly sized runs are the point and a long run climbing back up would
        # undo the week. Volume the sessions cannot carry is simply not run.
        if phase in ("taper", "race"):
            pass
        elif filler_days and per_filler > lr_km * 0.9:
            spill = (per_filler - lr_km * 0.9) * len(filler_days)
            per_filler = round(lr_km * 0.9, 1)
            lr_km = round(min(lr_km + spill, lr_cap, lr_ceilings[i]), 1)

        for d in run_days:
            day = wk_start + timedelta(days=d)
            if day < today:
                continue  # plan starts from today, not the past
            # Race week ends at the finish line — nothing scheduled after it.
            if phase == "race" and day > inp.race_date:
                continue

            if phase == "race" and d == inp.race_date.weekday():
                sessions.append(
                    _session(
                        day,
                        "race",
                        f"RACE — {inp.race_name or f'{inp.race_km:g} km'}",
                        inp.race_km,
                        int(projected),
                        [],
                        basis.paces["race"],
                        "Race day. Nothing to upload — go and run it.",
                    )
                )
                continue

            if d == long_day:
                dur = int(lr_km / ((long_p[0] + long_p[1]) / 2) * 1000)
                sessions.append(
                    _session(
                        day,
                        "long",
                        f"Long run {lr_km:g} km",
                        lr_km,
                        dur,
                        _steps_steady(dur, *long_p),
                        pace_label(threshold, "long"),
                        "Time on feet. Start slower than feels right.",
                    )
                )
            elif d == q_day:
                sessions.append(
                    _session(
                        day,
                        "quality",
                        q_title,
                        q_km,
                        q_dur,
                        q_steps,
                        q_pace_label,
                        q_note,
                    )
                )
            else:
                is_rec = len(run_days) >= 5 and d == filler_days[-1]
                p = rec_p if is_rec else easy_p
                km = max(3.0, per_filler)
                dur = int(km / ((p[0] + p[1]) / 2) * 1000)
                sessions.append(
                    _session(
                        day,
                        "recovery" if is_rec else "easy",
                        f"{'Recovery' if is_rec else 'Easy'} {km:g} km",
                        km,
                        dur,
                        _steps_steady(dur, *p),
                        pace_label(threshold, "recovery" if is_rec else "easy"),
                        None,
                    )
                )

        weeks.append(
            {
                "index": i + 1,
                "start": wk_start.isoformat(),
                "end": (wk_start + timedelta(days=6)).isoformat(),
                "phase": phase,
                "volume_km": round(sum(s["distance_km"] for s in sessions), 1),
                "planned_km": vol,
                "down_week": down,
                "sessions": sessions,
            }
        )

    weeks = [w for w in weeks if w["sessions"]]

    # Flag real week-on-week jumps against the recent high, not against the
    # previous week: rebounding off a planned down week is not overreaching.
    # Race week is excluded — the race itself is most of its volume.
    for i, cur in enumerate(weeks):
        if i == 0 or cur["phase"] == "race":
            continue
        recent_high = max(w["volume_km"] for w in weeks[max(0, i - 2) : i])
        if recent_high <= 0:
            continue
        if cur["volume_km"] - recent_high > 3.0 and cur["volume_km"] > recent_high * 1.12:
            warnings.append(
                f"Week {cur['index']} rises more than 10% over the preceding weeks "
                f"({recent_high:g} → {cur['volume_km']:g} km)."
            )

    # Does the plan ever build a long run worth the race distance?
    longest = max(
        (
            s["distance_km"]
            for w in weeks
            for s in w["sessions"]
            if s["kind"] == "long"
        ),
        default=0.0,
    )
    if inp.race_km >= 10 and longest < inp.race_km * 0.65:
        if longest >= lr_cap * 0.95:
            # Time on feet, not volume, is what stopped it — and the answer to
            # that is a faster long-run pace, not a longer long run. Saying "run
            # more" here would send them out for three and a half hours.
            mins = _interp(_LONG_RUN_MAX_MIN, inp.race_km)
            warnings.append(
                f"Longest run peaks at {longest:g} km for a {inp.race_km:g} km race, "
                f"which is the {mins:g} minutes this plan will ask you to spend on "
                "your feet. At your current long-run pace that is as far as three "
                "hours goes; the distance rises as the pace does."
            )
        else:
            warnings.append(
                f"Longest run peaks at {longest:g} km for a {inp.race_km:g} km race. "
                "Starting volume is the limit here — more weeks, or more running now, "
                "would be needed to prepare properly for the distance."
            )

    if inp.race_km >= 42 and total_weeks < 12:
        warnings.append(
            f"{total_weeks} weeks is short for a marathon — 16+ is the usual runway."
        )
    if inp.race_km >= 21 and total_weeks < 8:
        warnings.append(f"{total_weeks} weeks is a tight build for {inp.race_km:g} km.")

    # --- optional pace → heart-rate retarget --------------------------------
    # Deliberately last: every distance and duration above was derived from pace,
    # and stays that way. Only the target handed to the watch changes.
    hr_basis: dict[str, Any] | None = None
    if inp.target_mode == "hr":
        # Garmin's own configuration first — it reflects the athlete's real max
        # rather than whatever they happened to hit while training easy.
        configured = hr_zones or {}
        max_hr = configured.get("max_hr")
        zone_floors = configured.get("zone_floors")
        bands: list[tuple[float, int, int, str]] | None = None
        hr_ref: str | None = None
        hr_source = "garmin_zones"

        if max_hr and zone_floors:
            bands = bands_from_zone_floors(zone_floors, int(max_hr))
        elif max_hr:
            hr_source = "garmin_max_hr"  # configured max, but no zone ladder
        else:
            max_hr, hr_ref = estimate_max_hr(activities)
            hr_source = "recent_activities"

        if max_hr is None:
            warnings.append(
                "Asked for heart-rate targets but Garmin has no max HR configured and "
                "no recent run has usable HR data — kept pace targets."
            )
        else:
            max_hr = int(max_hr)
            for w in weeks:
                for s in w["sessions"]:
                    if s.get("spec") and s["spec"].get("steps"):
                        s["spec"]["steps"] = convert_targets_to_hr(
                            s["spec"]["steps"], basis.threshold_mps, max_hr, bands
                        )
                        # The row must say what the watch will actually chase,
                        # not the pace that happened to size the session.
                        s["hr_label"] = hr_label_for_steps(s["spec"]["steps"])
            if bands:
                zones = {label: f"{lo}–{hi} bpm" for _cut, lo, hi, label in bands}
            else:
                zones = {
                    label: f"{int(round(max_hr * lo))}–{int(round(max_hr * hi))} bpm"
                    for _cut, lo, hi, label in _HR_BANDS
                }
            hr_basis = {
                "max_hr": max_hr,
                "source": hr_source,
                "reference": hr_ref,
                "resting_hr": configured.get("resting_hr"),
                "zones": zones,
            }
            if hr_source == "recent_activities":
                warnings.append(
                    f"Garmin has no max HR configured, so these bands use {max_hr} bpm "
                    "— the highest seen in your recent runs. Training rarely reaches "
                    "true max, so if you know yours is higher, set it in Garmin "
                    "Connect and rebuild."
                )

    return {
        "target_mode": inp.target_mode if hr_basis else "pace",
        "hr_basis": hr_basis,
        "race_name": inp.race_name,
        "race_km": inp.race_km,
        "race_date": inp.race_date.isoformat(),
        "weeks_total": len(weeks),
        "runs_per_week": inp.runs_per_week,
        "long_run_day": inp.long_run_day,
        "peak_week_km": max((w["volume_km"] for w in weeks), default=0.0),
        "total_km": round(sum(w["volume_km"] for w in weeks), 1),
        "basis": {
            "source": basis.source,
            "threshold_mps": basis.threshold_mps,
            "threshold_pace": fmt_pace(basis.threshold_mps),
            "projected_race_time": basis.projected_race_time,
            "reference": basis.reference,
            "reference_activity_id": basis.reference_activity_id,
            "weekly_km_observed": basis.weekly_km_observed,
            "paces": basis.paces,
        },
        "warnings": warnings,
        "weeks": weeks,
    }

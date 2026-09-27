"""Strength training that serves the running block instead of competing with it.

Three sessions a week, deliberately placed on days the athlete already runs. That
is not a scheduling convenience — it is the point. Stacking strength onto running
days keeps the rest days genuinely restful; spreading them out leaves no day where
the body is left alone.

**The long-run day carries no loaded leg work.** That single rule shapes everything
else here. The long run is the week's biggest session and it happens in the morning;
putting squats on those legs that evening buys soreness that costs the next two runs
and returns nothing. The long-run day gets upper body and hip stability instead.

Volume is deliberately low and the reps deliberately few. This is strength for a
runner: enough to build tissue tolerance and economy, not enough to generate the
soreness that makes easy running hard. Hypertrophy work belongs to someone whose
Sunday is free.

Weights are not prescribed. The athlete's working loads are theirs to know, and a
number invented here would be either useless or dangerous. `weight_kg` is optional
throughout; sets and reps are the prescription.

Progression runs in four-week blocks that line up with the running plan's down
weeks (`base_plan.minutes_curve` backs off every fourth week), so the easy week is
easy everywhere rather than in one discipline at a time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.planner import DAYS

log = logging.getLogger(__name__)

#: Rest between sets, by role. Main lifts get longer — the set is the point, and
#: cutting rest turns a strength session into a conditioning one the legs will
#: still be paying for on Sunday.
REST_MAIN = 150
REST_SECONDARY = 105
REST_ACCESSORY = 75

#: (sets, reps, note) per four-week block. Every fourth week backs off to match
#: the running plan's down week.
PROGRESSION: list[tuple[int, int, str]] = [
    (3, 10, "Technique and tissue. Leave two reps in reserve on every set."),
    (4, 8, "Add load. Still two in reserve on the last set, not zero."),
    (4, 6, "Heaviest block. One rep in reserve; stop the set before form goes."),
    (3, 5, "Low volume, high quality. Sharpening, not building."),
]
DELOAD = (2, 8, "Down week — same movements, half the sets, comfortable load.")


@dataclass
class Exercise:
    name: str
    role: str = "secondary"  # "main" | "secondary" | "accessory"
    #: Fixed prescription for things progression should not touch: a plank is not
    #: better at 5 reps, and calves want volume regardless of the block.
    fixed_reps: int | None = None
    fixed_sets: int | None = None

    def rest(self) -> int:
        return {
            "main": REST_MAIN,
            "secondary": REST_SECONDARY,
        }.get(self.role, REST_ACCESSORY)


#: The one real leg day. Placed so at least 36 hours separate it from the next run.
LOWER = [
    Exercise("Barbell Back Squat", "main"),
    Exercise("Romanian Deadlift", "main"),
    Exercise("Calf Raise", "accessory", fixed_reps=15, fixed_sets=3),
    Exercise("Plank", "accessory", fixed_reps=1, fixed_sets=3),
]

#: Upper push/pull. Legs untouched, so it can sit the day before a long run.
UPPER_PUSH_PULL = [
    Exercise("Barbell Bench Press", "main"),
    Exercise("Bent-over Row with Barbell", "main"),
    Exercise("Barbell Overhead Press", "secondary"),
    Exercise("Dead Bug", "accessory", fixed_reps=10, fixed_sets=3),
]

#: Long-run day. Upper body and hips only — nothing that loads the legs under
#: weight on the morning they covered the week's longest run.
UPPER_ACCESSORY = [
    Exercise("Lat Pull-down", "secondary"),
    Exercise("Dumbbell Shoulder Press", "secondary"),
    Exercise("Barbell Hip Thrust on Floor", "accessory", fixed_reps=12, fixed_sets=3),
    Exercise("Bench Dip", "accessory", fixed_reps=10, fixed_sets=3),
    Exercise("Side Plank", "accessory", fixed_reps=1, fixed_sets=2),
]

#: Cardio machines that survive the round trip. Garmin validates the
#: (category, exercise) pair, so an exercise may only be used with its own
#: category — overriding it uploads cleanly and silently drops the name.
#:
#: Two machines are deliberately absent. A **ski erg** is not in the catalogue at
#: all. A **rowing machine** exists only as "Calorie Row", which Garmin files
#: under LATERAL_RAISE — its own miscategorisation — so it would show on the
#: watch as a shoulder exercise. Use "Cardio" for either and pick the machine on
#: the day; the step is ten easy minutes, not a prescription.
WARMUP_MACHINES = ["Treadmill", "Stair Stepper", "Elliptical"]
WARMUP_MINUTES = 10

FOCUS_LABEL = {
    "lower": "Lower body",
    "upper": "Upper body — push/pull",
    "upper_light": "Upper body + hips (long-run day)",
}


@dataclass
class StrengthInput:
    weeks: int = 14
    #: Weekday names for the gym sessions. Defaults to the running days so the
    #: rest days stay rest days.
    days: list[str] = field(default_factory=lambda: ["Wednesday", "Friday", "Sunday"])
    #: No loaded leg work lands on this day, whatever else the rotation wants.
    long_run_day: str = "Sunday"
    start_date: date | None = None
    plan_name: str | None = None
    #: Rotated across the week's sessions so the warm-up varies. Empty list
    #: drops the warm-up entirely; ["Cardio"] leaves the machine to the athlete.
    warmup_machines: list[str] = field(default_factory=lambda: list(WARMUP_MACHINES))
    warmup_minutes: int = WARMUP_MINUTES


def block_for_week(week_index: int, total_weeks: int) -> tuple[int, int, str, bool]:
    """(sets, reps, note, is_deload) for a 1-based week number.

    Down weeks are every fourth, matching `base_plan.minutes_curve`, except the
    final week — there is no point backing off into the end of the block.
    """
    if week_index % 4 == 0 and week_index != total_weeks:
        sets, reps, note = DELOAD
        return sets, reps, note, True
    block = min((week_index - 1) // 4, len(PROGRESSION) - 1)
    sets, reps, note = PROGRESSION[block]
    return sets, reps, note, False


def _session_spec(
    title: str,
    exercises: list[Exercise],
    sets: int,
    reps: int,
    warmup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = []
    for e in exercises:
        out.append(
            {
                "exercise_name": e.name,
                "sets": e.fixed_sets or sets,
                "reps": e.fixed_reps or reps,
                "rest_s": e.rest(),
            }
        )
    # Roughly: a set takes ~40s of work plus its rest.
    est = sum((x["sets"] * (40 + x["rest_s"])) for x in out)
    spec: dict[str, Any] = {
        "name": title[:100],
        "estimated_duration_s": int(est),
        "exercises": out,
    }
    if warmup:
        spec["warmup"] = warmup
        spec["estimated_duration_s"] = int(est + warmup["duration_s"])
    return spec


def build_strength_plan(inp: StrengthInput) -> dict[str, Any]:
    """A strength block shaped around the running week. Writes nothing."""
    today = inp.start_date or date.today()
    first_monday = today + timedelta(days=(7 - today.weekday()) % 7)

    day_idx = [DAYS.index(d) for d in inp.days if d in DAYS]
    if not day_idx:
        raise ValueError("no valid weekday names given for strength days")
    long_idx = DAYS.index(inp.long_run_day) if inp.long_run_day in DAYS else None

    # Assign a focus to each day: the long-run day never gets loaded legs, and the
    # remaining days alternate starting with the one real lower session.
    focuses: dict[int, str] = {}
    rotation = ["lower", "upper"]
    r = 0
    for d in sorted(day_idx):
        if d == long_idx:
            focuses[d] = "upper_light"
        else:
            focuses[d] = rotation[r % len(rotation)]
            r += 1

    plan_weeks: list[dict[str, Any]] = []
    for i in range(inp.weeks):
        n = i + 1
        sets, reps, note, deload = block_for_week(n, inp.weeks)
        wk_start = first_monday + timedelta(weeks=i)
        sessions = []
        for d in sorted(day_idx):
            focus = focuses[d]
            exercises = {
                "lower": LOWER,
                "upper": UPPER_PUSH_PULL,
                "upper_light": UPPER_ACCESSORY,
            }[focus]
            title = f"{FOCUS_LABEL[focus].split(' —')[0].split(' (')[0]} {sets}×{reps}"
            warmup = None
            if inp.warmup_machines and inp.warmup_minutes > 0:
                machine = inp.warmup_machines[
                    (i * len(day_idx) + sorted(day_idx).index(d))
                    % len(inp.warmup_machines)
                ]
                warmup = {
                    "exercise_name": machine,
                    "duration_s": inp.warmup_minutes * 60,
                }
            spec = _session_spec(title, exercises, sets, reps, warmup)
            sessions.append(
                {
                    "date": (wk_start + timedelta(days=d)).isoformat(),
                    "day": DAYS[d],
                    "focus": focus,
                    "focus_label": FOCUS_LABEL[focus],
                    "title": title,
                    "note": note,
                    "estimated_duration_s": spec["estimated_duration_s"],
                    "warmup": spec.get("warmup"),
                    "exercises": spec["exercises"],
                    "spec": spec,
                }
            )
        plan_weeks.append(
            {
                "index": n,
                "start": wk_start.isoformat(),
                "end": (wk_start + timedelta(days=6)).isoformat(),
                "sets": sets,
                "reps": reps,
                "deload": deload,
                "note": note,
                "sessions": sessions,
            }
        )

    return {
        "plan_name": inp.plan_name or "Strength",
        "weeks_total": len(plan_weeks),
        "days": [DAYS[d] for d in sorted(day_idx)],
        "long_run_day": inp.long_run_day,
        "sessions_per_week": len(day_idx),
        "weeks": plan_weeks,
        "notes": [
            "Weights are yours to set — the plan prescribes sets and reps only.",
            f"No loaded leg work on {inp.long_run_day}: the long run is that morning.",
            "Run in the morning, lift in the evening. Same day, so rest days stay rest days.",
            "Warm-up machine rotates; swap it for whatever is free.",
        ],
    }

"""The strength block's rules, stated as tests.

Pure computation over dates and a fixed exercise table, so none of this needs a
Garmin account. What is pinned here is the training logic, not the numbers for
their own sake — a change to `PROGRESSION` simply has to say which weeks it moved.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.strength_plan import (
    LOWER,
    PROGRESSION,
    UPPER_ACCESSORY,
    UPPER_PUSH_PULL,
    StrengthInput,
    block_for_week,
    build_strength_plan,
)

#: Categories that put the legs under load. Nothing from this set may land on
#: the long-run day — the rule the whole module is arranged around.
LOADED_LEG_CATEGORIES = {"SQUAT", "DEADLIFT", "LUNGE", "LEG_CURL", "OLYMPIC_LIFT"}

MONDAY = date(2026, 9, 28)


def _plan(**kw):
    kw.setdefault("start_date", date(2026, 9, 27))
    return build_strength_plan(StrengthInput(**kw))


def _category(name: str) -> str:
    from garminconnect.exercises import BY_NAME

    return BY_NAME[name]["category"]


def test_every_exercise_exists_in_the_garmin_catalogue():
    """A name that does not resolve uploads fine and shows blank on the watch."""
    from garminconnect.exercises import BY_NAME

    for group in (LOWER, UPPER_PUSH_PULL, UPPER_ACCESSORY):
        for ex in group:
            assert ex.name in BY_NAME, f"{ex.name!r} is not a Garmin exercise"


def test_long_run_day_carries_no_loaded_leg_work():
    plan = _plan(weeks=14, days=["Wednesday", "Friday", "Sunday"], long_run_day="Sunday")
    for week in plan["weeks"]:
        for session in week["sessions"]:
            if session["day"] != "Sunday":
                continue
            for ex in session["exercises"]:
                cat = _category(ex["exercise_name"])
                assert cat not in LOADED_LEG_CATEGORIES, (
                    f"week {week['index']}: {ex['exercise_name']} ({cat}) "
                    "landed on the long-run day"
                )


def test_long_run_day_rule_follows_the_day_not_the_name():
    """Move the long run to Wednesday and the leg work must move off it."""
    plan = _plan(weeks=4, days=["Wednesday", "Friday", "Sunday"], long_run_day="Wednesday")
    wednesdays = [
        s for w in plan["weeks"] for s in w["sessions"] if s["day"] == "Wednesday"
    ]
    assert wednesdays
    for session in wednesdays:
        assert session["focus"] == "upper_light"
        for ex in session["exercises"]:
            assert _category(ex["exercise_name"]) not in LOADED_LEG_CATEGORIES


def test_there_is_exactly_one_loaded_leg_day_per_week():
    """Running supplies the leg volume; one real lower session is the dose."""
    plan = _plan(weeks=6)
    for week in plan["weeks"]:
        lower = [s for s in week["sessions"] if s["focus"] == "lower"]
        assert len(lower) == 1, f"week {week['index']} has {len(lower)} lower days"


@pytest.mark.parametrize("week_index", [4, 8, 12])
def test_deload_weeks_line_up_with_the_running_block(week_index):
    """`base_plan.minutes_curve` backs off every fourth week; so does this."""
    sets, reps, _, deload = block_for_week(week_index, total_weeks=14)
    assert deload is True
    assert sets == 2


def test_final_week_never_deloads():
    _, _, _, deload = block_for_week(4, total_weeks=4)
    assert deload is False


def test_progression_advances_through_the_blocks():
    seen = [block_for_week(n, 14)[:2] for n in (1, 5, 9, 13)]
    assert seen == [(s, r) for s, r, _ in PROGRESSION]


def test_reps_fall_as_the_block_gets_heavier():
    reps = [block_for_week(n, 14)[1] for n in (1, 5, 9, 13)]
    assert reps == sorted(reps, reverse=True)


def test_fixed_prescriptions_ignore_progression():
    """A plank is not better at 5 reps, and calves want volume regardless."""
    early = _plan(weeks=14)["weeks"][0]
    late = _plan(weeks=14)["weeks"][12]

    def find(week, name):
        for s in week["sessions"]:
            for ex in s["exercises"]:
                if ex["exercise_name"] == name:
                    return ex
        raise AssertionError(f"{name} not scheduled")

    for name in ("Calf Raise", "Plank"):
        assert find(early, name)["reps"] == find(late, name)["reps"]


def test_weights_are_never_prescribed():
    plan = _plan(weeks=14)
    for week in plan["weeks"]:
        for session in week["sessions"]:
            for ex in session["exercises"]:
                assert "weight_kg" not in ex or ex["weight_kg"] is None


def test_sessions_land_on_the_requested_days_only():
    days = ["Tuesday", "Thursday"]
    plan = _plan(weeks=3, days=days, long_run_day="Sunday")
    got = {s["day"] for w in plan["weeks"] for s in w["sessions"]}
    assert got == set(days)
    assert plan["sessions_per_week"] == 2


def test_weeks_start_on_the_monday_after_the_anchor():
    plan = _plan(weeks=2, start_date=date(2026, 9, 27))  # a Sunday
    assert plan["weeks"][0]["start"] == MONDAY.isoformat()


def test_rejects_nonsense_weekday_names():
    with pytest.raises(ValueError):
        _plan(weeks=4, days=["Blursday"])


def test_warmup_machines_resolve_and_keep_their_own_category():
    """Garmin validates the (category, exercise) pair — override it and the
    exercise name is silently dropped, so the plan must never override."""
    from garminconnect.exercises import BY_NAME

    from app.strength_plan import WARMUP_MACHINES

    for machine in WARMUP_MACHINES:
        assert machine in BY_NAME, f"{machine!r} is not a Garmin exercise"

    plan = _plan(weeks=2)
    for week in plan["weeks"]:
        for s in week["sessions"]:
            assert s["warmup"] is not None
            assert "category" not in s["warmup"]


def test_warmup_rotates_across_sessions():
    plan = _plan(weeks=2, days=["Wednesday", "Friday", "Sunday"])
    first = [s["warmup"]["exercise_name"] for s in plan["weeks"][0]["sessions"]]
    assert len(set(first)) == 3, f"expected three different machines, got {first}"


def test_warmup_can_be_switched_off():
    plan = _plan(weeks=1, warmup_machines=[])
    for s in plan["weeks"][0]["sessions"]:
        assert s["warmup"] is None


def test_warmup_time_counts_towards_the_session_estimate():
    with_warm = _plan(weeks=1)["weeks"][0]["sessions"][0]
    without = _plan(weeks=1, warmup_machines=[])["weeks"][0]["sessions"][0]
    assert with_warm["estimated_duration_s"] - without["estimated_duration_s"] == 600


def test_main_lifts_rest_longer_than_accessories():
    week = _plan(weeks=1)["weeks"][0]
    lower = next(s for s in week["sessions"] if s["focus"] == "lower")
    squat = next(e for e in lower["exercises"] if e["exercise_name"] == "Barbell Back Squat")
    calves = next(e for e in lower["exercises"] if e["exercise_name"] == "Calf Raise")
    assert squat["rest_s"] > calves["rest_s"]

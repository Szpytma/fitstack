"""The shape of a whole block: phases, volume, long run, taper, replay.

`build_plan` is a pure function of (input, activities, zones), so a block built
from a fixed history is a fixed artefact. The golden case below is that
artefact. It is not there because the numbers are sacred — it is there because
the next change to `long_run_curve` or `volume_curve` should have to say out
loud which weeks it moved.

The invariants after it are the ones that must hold for *any* block, and they
are the real safety net: a taper that rises, or a long run that jumps 40% in a
week, is a bug whatever the golden numbers say.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import history

from app.planner import (
    MAX_LONG_SHARE,
    PlanInput,
    build_plan,
    long_run_cap,
    taper_weeks_for,
)

START = date(2026, 1, 5)  # a Monday
GOAL_S = 3 * 3600 + 30 * 60  # 3:30 marathon


def marathon_plan(**overrides) -> dict:
    """A 24-week marathon block off 40 km/week of steady history."""
    kwargs = dict(
        race_km=42.2,
        race_date=START + timedelta(weeks=23, days=6),
        start_date=START,
        goal_time_s=GOAL_S,
        runs_per_week=4,
    )
    kwargs.update(overrides)
    return build_plan(PlanInput(**kwargs), history(START, weeks=12, weekly_km=40))


def long_run_of(week: dict) -> float:
    """The week's long run, by kind.

    Not the longest session: a threshold workout with its warmup and cooldown
    can out-distance the long run in an early week, and measuring by distance
    would quietly test the wrong thing.
    """
    longs = [s["distance_km"] or 0 for s in week["sessions"] if s["kind"] == "long"]
    return max(longs) if longs else 0.0


# --------------------------------------------------------------------------
# golden case
# --------------------------------------------------------------------------

#: (phase, planned_km, long_run_km) per week of the golden marathon block.
GOLDEN = [
    ("base", 50.0, 15.0),
    ("base", 52.1, 15.7),
    ("base", 54.2, 16.5),
    ("base", 42.2, 13.8),
    ("base", 58.4, 17.9),
    ("base", 60.5, 18.7),
    ("base", 62.6, 19.4),
    ("base", 48.6, 16.1),
    ("build", 66.8, 20.9),
    ("build", 68.9, 21.6),
    ("build", 71.1, 22.3),
    ("build", 54.9, 18.4),
    ("build", 75.3, 23.8),
    ("build", 77.4, 24.5),
    ("build", 79.5, 25.2),
    ("peak", 61.2, 20.8),
    ("peak", 83.7, 27.6),
    ("peak", 85.8, 28.3),
    ("peak", 87.9, 28.9),
    ("peak", 90.0, 28.9),
    ("taper", 67.5, 16.9),
    ("taper", 49.5, 12.4),
    ("race", 36.0, 0.0),  # race week has no long run — it has a race
]


def test_golden_marathon_block():
    plan = marathon_plan()
    got = [
        (w["phase"], round(w["planned_km"], 1), round(long_run_of(w), 1))
        for w in plan["weeks"]
    ]

    assert len(got) == len(GOLDEN)
    for i, (want, have) in enumerate(zip(GOLDEN, got), start=1):
        assert have == want, f"week {i}: {have} != {want}"


# --------------------------------------------------------------------------
# invariants that hold for any block
# --------------------------------------------------------------------------

def test_weeks_are_one_based_and_contiguous():
    weeks = marathon_plan()["weeks"]

    assert [w["index"] for w in weeks] == list(range(1, len(weeks) + 1))
    for earlier, later in zip(weeks, weeks[1:]):
        assert date.fromisoformat(later["start"]) - date.fromisoformat(
            earlier["start"]
        ) == timedelta(weeks=1)


def test_the_block_ends_on_race_week():
    plan = marathon_plan()
    last = plan["weeks"][-1]

    assert last["phase"] == "race"
    assert date.fromisoformat(last["start"]) <= date.fromisoformat(plan["race_date"])
    assert date.fromisoformat(plan["race_date"]) <= date.fromisoformat(last["end"])


def test_taper_never_rises():
    """Neither volume nor long run may climb once the taper starts.

    A taper week that lands above the last build week is the failure mode that
    `_hold_scale` also guards in `adapt.py` — worth pinning on the planner side
    too, since it is the planner that shapes the week.
    """
    weeks = marathon_plan()["weeks"]
    taper = [w for w in weeks if w["phase"] in ("taper", "race")]
    last_build = [w for w in weeks if w["phase"] not in ("taper", "race")][-1]

    assert taper, "a marathon block must taper"
    ceiling_km = last_build["planned_km"]
    ceiling_long = long_run_of(last_build)
    for w in taper:
        assert w["planned_km"] <= ceiling_km
        assert long_run_of(w) <= ceiling_long
        ceiling_km = w["planned_km"]
        ceiling_long = long_run_of(w)


def test_long_run_progression_survives_the_spill_rule():
    """Spill from the filler days must not push the long run past its ceiling.

    This was a real regression: the week assembly tops the long run up with
    whatever the other days could not absorb, and that top-up has to respect the
    same 10% progression clamp as the curve itself.
    """
    weeks = marathon_plan()["weeks"]
    cap = long_run_cap(42.2)

    longest_so_far = 0.0
    for w in weeks:
        lr = long_run_of(w)
        assert lr <= cap + 0.05, f"week {w['index']}: {lr} km over the cap {cap}"
        assert lr <= w["volume_km"] * MAX_LONG_SHARE + 0.05
        if longest_so_far:
            assert lr <= longest_so_far * 1.10 + 0.05, (
                f"week {w['index']}: {lr} km is more than 10% over {longest_so_far}"
            )
        longest_so_far = max(longest_so_far, lr)


def test_the_first_long_runs_are_held_near_the_longest_recent_one():
    """The guard that binds when the plan meets an athlete it outruns.

    40 km weeks made of short runs: the curve wants a 15.5 km long run in week
    one, the athlete's longest in the last 30 days is 8 km. Beyond about 110%
    of that, a single run carries materially higher overuse risk whatever the
    weekly volume says — so the block starts where the athlete is and climbs.
    """
    plan = build_plan(
        PlanInput(
            race_km=42.2,
            race_date=START + timedelta(weeks=23, days=6),
            start_date=START,
            goal_time_s=GOAL_S,
            runs_per_week=4,
        ),
        history(START, weeks=12, weekly_km=40, runs=6, long_share=8 / 40),
    )
    longs = [long_run_of(w) for w in plan["weeks"]]

    assert longs[0] <= 8.0 * 1.10 + 0.05
    # Every step forward stays inside the same 10%, all the way up the ramp.
    reached = 8.0
    for i, lr in enumerate(longs, start=1):
        assert lr <= reached * 1.10 + 0.05, f"week {i}: {lr} km off {reached} km"
        reached = max(reached, lr)
    assert any("longest run in the last 30 days" in w for w in plan["warnings"])
    # It is a held start, not a ceiling for the block: the ramp still gets there.
    assert max(longs) > 25


def test_down_weeks_are_lighter_than_the_week_before():
    for w, prev in zip(marathon_plan()["weeks"][1:], marathon_plan()["weeks"]):
        if w["down_week"]:
            assert w["planned_km"] < prev["planned_km"]


def test_volume_km_tracks_planned_km():
    """`volume_km` is the sum of rounded sessions; `planned_km` is the target.

    They are allowed to differ — the anchor deliberately uses `planned_km` —
    but not by much, or the week on screen is not the week that was planned.
    """
    for w in marathon_plan()["weeks"]:
        if w["phase"] == "race":
            continue  # the race itself is not training volume
        assert abs(w["volume_km"] - w["planned_km"]) <= max(1.5, w["planned_km"] * 0.05)


# --------------------------------------------------------------------------
# replay
# --------------------------------------------------------------------------

def test_replay_is_identical():
    """The guarantee the whole rolling plan rests on."""
    assert marathon_plan() == marathon_plan()


def test_replay_is_identical_from_a_later_today():
    """Same start date, same history, later clock — same calendar weeks.

    `active_plan` replays a block by pinning `start_date`, so the same inputs
    must produce the same weeks however long ago the plan was started.
    """
    first = marathon_plan()
    later = build_plan(
        PlanInput(
            race_km=42.2,
            race_date=START + timedelta(weeks=23, days=6),
            start_date=START,
            goal_time_s=GOAL_S,
            runs_per_week=4,
        ),
        # The athlete has kept running since; the calendar must not move.
        history(START + timedelta(weeks=6), weeks=12, weekly_km=40),
    )

    assert [w["start"] for w in later["weeks"]] == [w["start"] for w in first["weeks"]]
    assert [w["phase"] for w in later["weeks"]] == [w["phase"] for w in first["weeks"]]


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------

def test_race_inside_a_week_is_refused():
    with pytest.raises(ValueError):
        build_plan(
            PlanInput(race_km=10, race_date=START + timedelta(days=3), start_date=START,
                      goal_time_s=45 * 60),
            history(START, weeks=8, weekly_km=30),
        )


def test_no_history_and_no_goal_time_is_refused():
    with pytest.raises(ValueError):
        build_plan(
            PlanInput(race_km=42.2, race_date=START + timedelta(weeks=16),
                      start_date=START),
            [],
        )


def test_short_marathon_block_warns_with_the_runway_it_quotes():
    plan = build_plan(
        PlanInput(race_km=42.2, race_date=START + timedelta(weeks=11, days=6),
                  start_date=START, goal_time_s=GOAL_S),
        history(START, weeks=12, weekly_km=40),
    )
    runway = [w for w in plan["warnings"] if "runway" in w]

    assert runway, "a 12-week marathon block must say so"
    assert "16+" in runway[0]


def test_taper_length_follows_the_distance():
    assert taper_weeks_for(42.2) >= taper_weeks_for(21.1) >= taper_weeks_for(10)

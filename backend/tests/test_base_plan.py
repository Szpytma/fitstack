"""Aerobic base mode: heart rate in, minutes out.

Three inversions against the race planner, and they are the whole point. The
band is the prescription rather than a translation of pace. Progression is in
minutes, because at a fixed heart rate distance is an outcome. And the band is
never inferred — without configured zones this refuses to build at all.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import history

from app.base_plan import BaseInput, build_base_plan, zone2_band

START = date(2026, 1, 5)
ZONES = {"max_hr": 186, "zone_floors": [93, 121, 140, 158, 172]}


def base_plan(**overrides) -> dict:
    kwargs = dict(weeks=8, runs_per_week=4, start_date=START, weekly_minutes=240)
    kwargs.update(overrides)
    return build_base_plan(
        BaseInput(**kwargs), history(START, weeks=8, weekly_km=40), ZONES
    )


def test_zone2_band_comes_from_the_configured_floors():
    band = zone2_band(ZONES)

    assert band == (121, 139, 140)


def test_zone2_band_is_not_guessed_from_a_partial_setup():
    assert zone2_band(None) is None
    assert zone2_band({"max_hr": 186}) is None
    assert zone2_band({"zone_floors": [100, 120]}) is None
    assert zone2_band({"zone_floors": [0, 0, 0]}) is None


def test_building_without_zones_is_refused():
    """The band is the workout, so there is nothing to fall back to."""
    with pytest.raises(ValueError, match="heart rate zones"):
        build_base_plan(BaseInput(weeks=8, start_date=START), [], None)


def test_an_explicit_band_is_accepted_in_place_of_zones():
    plan = build_base_plan(
        BaseInput(weeks=4, start_date=START, weekly_minutes=200,
                  hr_floor=120, hr_ceiling=139),
        history(START, weeks=8, weekly_km=40),
        None,
    )

    assert plan["weeks"]


def test_progression_is_in_minutes():
    """`planned_minutes` is the target; distance is only an estimate from EF."""
    weeks = base_plan()["weeks"]

    assert all(w.get("planned_minutes") for w in weeks)
    first, last_build = weeks[0], max(weeks, key=lambda w: w["planned_minutes"])
    assert last_build["planned_minutes"] > first["planned_minutes"]


def test_every_session_targets_heart_rate_not_pace():
    for w in base_plan()["weeks"]:
        for s in w["sessions"]:
            steps = s["spec"]["steps"]
            assert steps, f"{s['title']} has no steps"
            assert any("hr" in str(step).lower() for step in steps)


def test_the_block_is_open_ended():
    """No race, no taper: the last week is not a wind-down."""
    weeks = base_plan(weeks=10)["weeks"]

    assert len(weeks) == 10
    assert all(w["phase"] not in ("taper", "race") for w in weeks)


def test_down_weeks_still_land():
    """Open-ended is not the same as monotonic — recovery weeks remain."""
    weeks = base_plan(weeks=12)["weeks"]

    assert any(w["down_week"] for w in weeks)
    for w, prev in zip(weeks[1:], weeks):
        if w["down_week"]:
            assert w["planned_minutes"] < prev["planned_minutes"]


def test_replay_is_identical():
    assert base_plan() == base_plan()


def test_output_shape_matches_the_race_planner():
    """So the rolling-week machinery and the Garmin push work on it unchanged."""
    plan = base_plan()
    week = plan["weeks"][0]

    assert {"weeks", "warnings"} <= set(plan)
    assert {"index", "start", "end", "phase", "sessions", "down_week"} <= set(week)
    assert {"date", "kind", "title", "spec"} <= set(week["sessions"][0])
    assert date.fromisoformat(week["end"]) - date.fromisoformat(
        week["start"]
    ) == timedelta(days=6)

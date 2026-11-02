"""The rolling plan's anchor: why a week at a time still adds up to a block.

A rolling plan cannot be stateless. Regenerating a week with `start_date =
today` looks right and is silently broken: `total_weeks` shrinks by one each
week, so the block never leaves base phase and never tapers. `ActivePlan` pins
`start_date` and `anchor_weekly_km` to prevent exactly that, and these tests
are what stops someone simplifying the pins away.

Nothing here touches disk: `rebuild` is a pure function of the pinned anchor
plus whatever history it is handed.
"""

from __future__ import annotations

from datetime import date, timedelta

from conftest import history, week_of
from test_block_shape import GOAL_S, START, marathon_plan

from app import active_plan
from app.active_plan import ActivePlan


def plan_state(**overrides) -> ActivePlan:
    kwargs = dict(
        race_km=42.2,
        race_date=START + timedelta(weeks=23, days=6),
        start_date=START,
        anchor_weekly_km=active_plan.anchor_from_plan(marathon_plan()),
        runs_per_week=4,
        goal_time_s=GOAL_S,
    )
    kwargs.update(overrides)
    return ActivePlan(**kwargs)


def test_the_anchor_is_the_curves_target_not_the_rounded_sessions():
    """`planned_km`, never `volume_km` — only the former replays identically."""
    plan = marathon_plan()
    first = plan["weeks"][0]

    assert active_plan.anchor_from_plan(plan) == first["planned_km"]


def test_rebuild_is_stable_across_calls():
    state = plan_state()
    acts = history(START, weeks=12, weekly_km=40)

    assert active_plan.rebuild(state, acts) == active_plan.rebuild(state, acts)


def test_volume_holds_when_history_swells():
    """Paces float, volume is pinned.

    A heavy fortnight must not drag the whole block up: the ramp replays from
    the anchor, not from whatever the athlete has been doing lately.
    """
    state = plan_state()
    calm = active_plan.rebuild(state, history(START, weeks=12, weekly_km=40))
    heavy = active_plan.rebuild(state, history(START, weeks=12, weekly_km=80))

    assert [w["planned_km"] for w in heavy["weeks"]] == [
        w["planned_km"] for w in calm["weeks"]
    ]


def test_the_phase_arc_advances_instead_of_restarting():
    """The failure a stateless rebuild produces: base forever, no taper.

    Replaying from the pinned start date keeps `total_weeks` fixed, so week 20
    of the block is still week 20 however many weeks later it is asked for.
    """
    state = plan_state()
    acts = history(START, weeks=12, weekly_km=40)
    block = active_plan.rebuild(state, acts)

    phases = [w["phase"] for w in block["weeks"]]
    assert phases[0] == "base"
    assert "build" in phases and "peak" in phases
    assert phases[-1] == "race"
    assert "taper" in phases


def test_selecting_a_week_by_its_monday():
    state = plan_state()
    block = active_plan.rebuild(state, history(START, weeks=12, weekly_km=40))

    # Weeks are anchored backwards from race week, so week one's Monday comes
    # from the block itself rather than from the start date.
    first_monday = date.fromisoformat(block["weeks"][0]["start"])
    third = active_plan.select_week(block, first_monday + timedelta(weeks=2))

    assert third is not None
    assert third["index"] == 3
    assert active_plan.select_week(block, first_monday - timedelta(weeks=1)) is None


def test_week_scale_shapes_the_sessions_rather_than_scaling_them_after():
    """A held week is built at the lower volume, caps and spill included."""
    state = plan_state()
    acts = history(START, weeks=12, weekly_km=40)

    full = active_plan.rebuild(state, acts)
    held = active_plan.rebuild(state, acts, week_scale={5: 0.8})

    assert held["weeks"][4]["planned_km"] < full["weeks"][4]["planned_km"]
    # Only that week moves — the ramp either side is untouched.
    assert held["weeks"][3]["planned_km"] == full["weeks"][3]["planned_km"]
    assert held["weeks"][5]["planned_km"] == full["weeks"][5]["planned_km"]
    # And the long run was re-shaped, not clipped off the end.
    longest = max(s["distance_km"] or 0 for s in held["weeks"][4]["sessions"])
    assert longest <= held["weeks"][4]["volume_km"]


def test_a_stateless_rebuild_would_lose_the_taper():
    """Why the pins exist, stated as a test rather than a comment.

    Rebuilding with `start_date = today` six weeks in gives a shorter block that
    is still in base phase where the pinned one is already building.
    """
    six_weeks_in = START + timedelta(weeks=6)
    pinned = active_plan.rebuild(plan_state(), history(START, weeks=12, weekly_km=40))
    stateless = active_plan.rebuild(
        plan_state(start_date=six_weeks_in),
        history(six_weeks_in, weeks=12, weekly_km=40),
    )

    assert len(stateless["weeks"]) < len(pinned["weeks"])
    # Same calendar week, two different places on the ramp: the stateless
    # rebuild has restarted its volume curve from the bottom.
    assert pinned["weeks"][6]["planned_km"] > stateless["weeks"][0]["planned_km"]
    # And it has shed a week of runway, which is how the taper gets eaten.
    assert pinned["weeks_total"] - stateless["weeks_total"] == 6


def test_status_reports_the_pins_it_replays_from():
    state = plan_state()
    status = active_plan.status(state, today=START + timedelta(weeks=3))

    assert status["started"] == START.isoformat()
    assert status["anchor_weekly_km"] == state.anchor_weekly_km
    assert date.fromisoformat(status["race_date"]) == state.race_date
    # The lead-in is part of the answer: a block capped shorter than the runway
    # does not open on the day the plan is started.
    assert status["lead_in_weeks"] >= 0
    assert status["block_weeks"] == len(
        active_plan.rebuild(state, history(START, weeks=12, weekly_km=40))["weeks"]
    )


def test_compliance_reports_a_base_week_in_minutes_not_kilometres():
    """The card on `/plan` has to agree with the engine that judges the week.

    `adapt.decide` measures a base block in minutes, because at a fixed heart
    rate distance is an outcome. `compliance` once measured the same week in
    kilometres on its own, so a week run slower than planned — exactly what a
    hot day or a tired leg produces — showed as *over* target on screen while
    the engine saw a shortfall. Same week, two numbers, and the one the athlete
    could see was the wrong one.
    """
    week = {
        "index": 1,
        "start": "2026-09-28",
        "end": "2026-10-04",
        "planned_km": 24.6,
        "planned_minutes": 240,
        "sessions": [{}, {}, {}, {}],
    }
    plan = {"weeks": [week, {"index": 2, "start": "2026-10-05", "end": "2026-10-11"}]}
    # Four runs that hit 240 minutes exactly while falling well short on
    # distance — the signature of honest zone 2 running on a bad day.
    slow = [
        {
            "type": "running",
            "start_local": f"2026-09-{day} 07:00",
            "distance_m": 5000,
            "duration_s": 60 * 60,
            "avg_hr": 140,
            "avg_speed_mps": 5000 / 3600,
        }
        for day in ("28", "29", "30")
    ] + [
        {
            "type": "running",
            "start_local": "2026-10-01 07:00",
            "distance_m": 5000,
            "duration_s": 60 * 60,
            "avg_hr": 140,
            "avg_speed_mps": 5000 / 3600,
        }
    ]

    got = active_plan.compliance(
        plan, week_number=2, activities=slow, today=date(2026, 10, 5), max_hr=200
    )

    assert got is not None
    assert got["unit"] == "min"
    assert got["planned_minutes"] == 240
    assert got["actual_minutes"] == 240
    assert got["ratio"] == 1.0  # on target, in the unit that was prescribed
    # In kilometres the same week reads as a 19% shortfall. That is the figure
    # the card used to show, and it would have had the athlete chasing pace.
    assert got["actual_km"] == 20.0
    assert round(got["actual_km"] / got["planned_km"], 2) == 0.81
    assert got["runs_done"] == 4
    assert got["runs_planned"] == 4


def test_compliance_still_reports_a_race_week_in_kilometres():
    """A race block prescribes distance, so nothing changes there."""
    week = {
        "index": 1,
        "start": "2026-09-28",
        "end": "2026-10-04",
        "planned_km": 40.0,
        "sessions": [{}, {}],
    }
    plan = {"weeks": [week, {"index": 2, "start": "2026-10-05", "end": "2026-10-11"}]}
    got = active_plan.compliance(
        plan,
        week_number=2,
        activities=week_of(date(2026, 9, 28), 32.0, runs=2),
        today=date(2026, 10, 5),
        max_hr=200,
    )

    assert got is not None
    assert got["unit"] == "km"
    assert got["planned_minutes"] is None
    assert got["ratio"] == 0.8

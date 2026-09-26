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

from conftest import history
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

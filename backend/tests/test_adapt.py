"""Week-to-week adaptation: when the plan holds, steps back, or carries on.

Every rule here needs the same signal in two consecutive weeks. With four runs
a week one week is too small a sample, and a plan that lurches every seven days
has stopped being a plan — so "one bad week changes nothing" is as much a test
as any of the rules themselves.
"""

from __future__ import annotations

from datetime import date, timedelta

from conftest import run
from test_block_shape import marathon_plan

from app import adapt

PLAN = marathon_plan()


def week(n: int) -> dict:
    return PLAN["weeks"][n - 1]


def monday_of(n: int) -> date:
    return date.fromisoformat(week(n)["start"])


def after(n: int) -> date:
    """A day inside week n+1, so weeks up to n count as finished."""
    return date.fromisoformat(week(n)["end"]) + timedelta(days=1)


def ran(n: int, share: float, runs: int = 4, **kw) -> list[dict]:
    """`share` of week n's planned kilometres, spread over `runs` runs."""
    km = week(n)["planned_km"] * share / runs
    return [run(monday_of(n) + timedelta(days=i), km, **kw) for i in range(runs)]


def test_a_single_short_week_changes_nothing():
    """One week is not evidence — the second one is."""
    acts = ran(1, 1.0) + ran(2, 0.4)

    d = adapt.decide(PLAN, week_number=3, activities=acts, today=after(2))

    assert d.action == "advance"
    assert d.scale == 1.0


def test_two_short_weeks_hold_the_volume():
    acts = ran(1, 0.4) + ran(2, 0.4)

    d = adapt.decide(PLAN, week_number=3, activities=acts, today=after(2))

    assert d.action == "hold"
    assert d.scale <= 1.0
    assert "below 70%" in " ".join(d.reasons)


def test_two_empty_weeks_step_back():
    d = adapt.decide(PLAN, week_number=3, activities=[], today=after(2))

    assert d.action == "step_back"
    assert d.scale == adapt.STEP_BACK


def test_two_big_weeks_hold_so_the_extra_does_not_compound():
    acts = ran(1, 1.5) + ran(2, 1.5)

    d = adapt.decide(PLAN, week_number=3, activities=acts, today=after(2))

    assert d.action == "hold"
    assert d.scale <= 1.0


def test_a_hold_never_raises_volume_into_a_down_week():
    """The clamp that matters.

    Levelling at the previous week lands *above* plan whenever the upcoming
    week is already lighter — every down week, every taper week. Week 4 of this
    block is a down week, so holding into it must not lift it back up.
    """
    down = next(w for w in PLAN["weeks"] if w["down_week"] and w["index"] > 2)
    n = int(down["index"])
    assert down["planned_km"] < week(n - 1)["planned_km"]

    acts = ran(n - 2, 0.4) + ran(n - 1, 0.4)
    d = adapt.decide(PLAN, week_number=n, activities=acts, today=after(n - 1))

    assert d.action == "hold"
    assert d.scale <= 1.0
    assert down["planned_km"] * d.scale <= down["planned_km"]


def test_a_hold_in_the_taper_cannot_undo_it():
    taper = [w for w in PLAN["weeks"] if w["phase"] == "taper"]
    n = int(taper[-1]["index"])

    acts = ran(n - 2, 0.4) + ran(n - 1, 0.4)
    d = adapt.decide(PLAN, week_number=n, activities=acts, today=after(n - 1))

    assert d.scale <= 1.0


def test_weeks_still_running_are_not_evidence():
    """A week that has not ended yet cannot be judged, however empty it looks."""
    d = adapt.decide(PLAN, week_number=2, activities=ran(1, 1.0), today=after(1))

    assert d.action == "advance"
    assert "Only 1 finished week" in " ".join(d.reasons)


# --------------------------------------------------------------------------
# efficiency factor
# --------------------------------------------------------------------------

def test_efficiency_factor_ignores_a_time_trial():
    """A hard effort posts a high EF and says nothing about easy running."""
    hard = run(monday_of(1), 10, pace_s_per_km=240, avg_hr=178)

    assert adapt.efficiency_factor(hard, max_hr=190) is None


def test_efficiency_factor_ignores_an_interval_session():
    from conftest import laps_reps

    session = run(monday_of(1), 14, pace_s_per_km=300, avg_hr=150, laps=laps_reps())

    assert adapt.efficiency_factor(session, max_hr=190) is None


def test_efficiency_factor_reads_an_aerobic_run():
    easy = run(monday_of(1), 12, pace_s_per_km=330, avg_hr=140)
    ef = adapt.efficiency_factor(easy, max_hr=190)

    assert ef is not None
    # metres per minute per heartbeat: (3.03 m/s * 60) / 140
    assert 1.2 <= ef <= 1.4


def test_the_same_pace_at_a_higher_heart_rate_reads_lower():
    cheap = run(monday_of(1), 12, pace_s_per_km=330, avg_hr=135)
    dear = run(monday_of(1), 12, pace_s_per_km=330, avg_hr=150)

    assert adapt.efficiency_factor(cheap, 190) > adapt.efficiency_factor(dear, 190)


def test_declining_efficiency_holds_volume():
    """Doing the work, but paying more heartbeats for it, two weeks running."""
    baseline = [
        run(monday_of(1) - timedelta(days=d), 12, pace_s_per_km=330, avg_hr=135)
        for d in (7, 10, 14, 17, 21)
    ]
    costly = [
        run(monday_of(n) + timedelta(days=i), week(n)["planned_km"] / 4,
            pace_s_per_km=330, avg_hr=160)
        for n in (1, 2)
        for i in range(4)
    ]

    d = adapt.decide(
        PLAN,
        week_number=3,
        activities=baseline + costly,
        max_hr=190,
        today=after(2),
        plan_start=monday_of(1),
    )

    assert d.action == "hold"
    assert d.scale == adapt.STRUGGLE_HOLD


def test_a_week_ending_today_counts_as_finished():
    """The designed cadence is "ask after the Sunday long run" — so on that
    Sunday the week just run has to be evidence, not still in progress."""
    from datetime import date

    from app import adapt

    plan = {
        "weeks": [
            {
                "index": 1,
                "start": "2026-09-21",
                "end": "2026-09-27",
                "planned_km": 25.0,
                "sessions": [],
            },
            {
                "index": 2,
                "start": "2026-09-28",
                "end": "2026-10-04",
                "planned_km": 26.0,
                "sessions": [],
            },
        ]
    }
    on_the_sunday = adapt.completed_weeks(
        plan, before_week=2, activities=[], max_hr=211, today=date(2026, 9, 27)
    )
    assert [w.week_number for w in on_the_sunday] == [1]

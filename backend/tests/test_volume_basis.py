"""`weekly_volume` — what the history says the athlete can start from.

The figure this returns anchors the whole block, so the edge cases matter more
than the happy path: a number that under-reads produces a plan whose long run
never reaches race distance.
"""

from __future__ import annotations

from datetime import date, timedelta

from conftest import history, run, week_of

from app.planner import LONG_RUN_VOLUME_RATIO, observed_weekly_km, weekly_volume


def test_steady_history_reads_its_own_volume(monday: date):
    acts = history(monday, weeks=8, weekly_km=40)
    basis = weekly_volume(acts, today=monday + timedelta(days=6))

    assert basis.median_km == 40.0
    assert basis.start_km is not None
    # The four-week mean reads slightly over 40 because its 28-day window is
    # inclusive at both ends; the figure still has to describe this athlete.
    assert 38 <= basis.start_km <= 46


def test_no_history_has_no_starting_volume(monday: date):
    basis = weekly_volume([], today=monday)

    assert basis.start_km is None
    assert basis.longest_run_km is None


def test_non_running_activities_do_not_count(monday: date):
    rides = [run(monday + timedelta(days=i), 30, kind="cycling") for i in range(5)]
    basis = weekly_volume(rides, today=monday + timedelta(days=6))

    assert basis.start_km is None


def test_returning_from_a_break_is_not_read_as_the_recent_mean(monday: date):
    """The case the median exists for.

    Three solid weeks, a month off, then two short weeks back. A four-week mean
    describes a week this runner has never run; the median of the weeks they
    actually ran describes one they have.
    """
    today = monday + timedelta(days=6)
    acts: list[dict] = []
    for w in (11, 10, 9):  # the solid block, ~10 weeks ago
        acts += week_of(monday - timedelta(weeks=w), 30)
    for w in (1, 0):  # back running, but only just
        acts += week_of(monday - timedelta(weeks=w), 9, runs=3)

    basis = weekly_volume(acts, today=today)
    recent = observed_weekly_km(acts, today=today)

    assert basis.start_km is not None
    assert recent is not None
    # Above the four-week mean, because those weeks are not the whole athlete...
    assert basis.start_km > recent
    # ...but cut for the time off rather than restored to the old 30 km.
    assert basis.start_km < 30


def test_faded_volume_is_capped_by_the_longest_recent_run(monday: date):
    """A big past and short runs now: the long run caps what the median may claim.

    Eight weeks of 60 km, then a month of 10 km weeks whose longest run is 5 km.
    The median still says 60; what they can be started on does not.
    """
    acts: list[dict] = []
    for w in range(12, 4, -1):
        acts += week_of(monday - timedelta(weeks=w), 60, runs=7, long_share=8 / 60)
    for w in (3, 2, 1, 0):
        acts += week_of(monday - timedelta(weeks=w), 10, runs=2, long_share=0.5)

    basis = weekly_volume(acts, today=monday + timedelta(days=6))

    assert basis.median_km == 60.0
    assert basis.start_km is not None
    assert basis.longest_run_km is not None
    assert basis.start_km <= basis.longest_run_km * LONG_RUN_VOLUME_RATIO + 0.1
    assert basis.start_km < basis.median_km / 2


def test_the_recent_mean_is_a_floor_the_cap_cannot_undercut(monday: date):
    """Whatever else is true, they are running what they are running.

    Seven 8 km runs a week is 56 km off a 8 km longest run — the long-run cap
    would say 20. The floor wins, because the weeks happened.
    """
    acts: list[dict] = []
    for w in range(6):
        acts += week_of(monday - timedelta(weeks=w), 56, runs=7, long_share=8 / 56)

    basis = weekly_volume(acts, today=monday + timedelta(days=6))

    assert basis.recent_km is not None
    assert basis.start_km == basis.recent_km
    assert basis.start_km > basis.longest_run_km * LONG_RUN_VOLUME_RATIO


def test_basis_survives_a_round_trip_through_json(monday: date):
    basis = weekly_volume(history(monday, weeks=6, weekly_km=35), today=monday)
    payload = basis.as_json()

    assert set(payload) >= {"start_km", "recent_km", "longest_run_km"}

"""`adapt.week_series` — the calendar-week rollup the stats page is drawn from.

`report_week` answers "how did plan week 5 go". This answers "what has the
training looked like", which spans the weeks before the block and has no
opinion about what was planned. The distinctions pinned here are the ones that
make the chart honest.
"""

from __future__ import annotations

from datetime import date, timedelta

from app import adapt

from conftest import run, week_of

MAX_HR = 200


def test_buckets_by_iso_week_not_by_seven_day_blocks() -> None:
    """A week starts on Monday, whatever day the first run happened to be."""
    wed = date(2026, 10, 7)  # a Wednesday
    series = adapt.week_series(
        [run(wed, 10.0), run(wed + timedelta(days=3), 10.0)], MAX_HR
    )
    assert len(series) == 1
    assert series[0]["week_start"] == "2026-10-05"
    assert series[0]["week_end"] == "2026-10-11"
    assert series[0]["runs"] == 2


def test_weeks_without_runs_are_absent_not_zero() -> None:
    """A gap in training is not a week of zero volume.

    Emitting zeros would draw a bar at the baseline for a fortnight nobody
    measured, and a reader would take that as "ran nothing" rather than "no
    data" — which are different facts when the athlete was ill or abroad.
    """
    first = date(2026, 9, 7)
    series = adapt.week_series(
        [run(first, 10.0), run(first + timedelta(weeks=3), 10.0)], MAX_HR
    )
    assert [w["week_start"] for w in series] == ["2026-09-07", "2026-09-28"]


def test_oldest_first() -> None:
    mon = date(2026, 8, 3)
    series = adapt.week_series(
        [run(mon + timedelta(weeks=2), 8.0), run(mon, 8.0), run(mon + timedelta(weeks=1), 8.0)],
        MAX_HR,
    )
    assert [w["week_start"] for w in series] == ["2026-08-03", "2026-08-10", "2026-08-17"]


def test_since_keeps_one_training_era_in_frame() -> None:
    """EF is not comparable across eras, so the caller must be able to cut.

    A short effort at the top of the aerobic window posts a higher EF than
    genuinely easy running, so last year's 5K efforts out-score this year's base
    block. `since` is the only guard against that comparison.
    """
    old = date(2025, 7, 21)
    recent = date(2026, 9, 21)
    acts = [run(old, 10.0), run(recent, 10.0)]
    assert len(adapt.week_series(acts, MAX_HR)) == 2
    cut = adapt.week_series(acts, MAX_HR, since=date(2026, 5, 18))
    assert [w["week_start"] for w in cut] == ["2026-09-21"]


def test_counts_only_runs() -> None:
    mon = date(2026, 10, 5)
    series = adapt.week_series(
        [run(mon, 10.0), run(mon + timedelta(days=1), 40.0, kind="cycling")], MAX_HR
    )
    assert series[0]["runs"] == 1
    assert series[0]["km"] == 10.0


def test_ef_median_is_reported_with_its_sample_count() -> None:
    """A week's EF is a median, and how many runs it rests on is part of it.

    One aerobic run out of four is a far weaker claim than four out of four,
    and the chart has to be able to say so.
    """
    mon = date(2026, 10, 5)
    acts = week_of(mon, 40.0, runs=4, avg_hr=140)
    series = adapt.week_series(acts, MAX_HR)
    assert series[0]["ef_runs"] == 4
    assert series[0]["ef_median"] is not None


def test_ef_is_none_when_no_run_was_aerobic() -> None:
    """A week of hard running is a week with no EF measurement, not a zero.

    At 0.95 of max every run is outside the aerobic window, so nothing that
    week says anything about whether easy running is getting cheaper.
    """
    mon = date(2026, 10, 5)
    series = adapt.week_series(week_of(mon, 40.0, avg_hr=190), MAX_HR)
    assert series[0]["ef_median"] is None
    assert series[0]["ef_runs"] == 0
    # The volume still counts — only the effort measure is missing.
    assert series[0]["runs"] == 4
    assert series[0]["actual_minutes"] > 0


def test_volume_totals_match_the_activities() -> None:
    mon = date(2026, 10, 12)
    series = adapt.week_series([run(mon, 10.0, pace_s_per_km=360.0)], MAX_HR)
    assert series[0]["km"] == 10.0
    assert series[0]["actual_minutes"] == 60


def test_no_runs_at_all_is_an_empty_series() -> None:
    assert adapt.week_series([], MAX_HR) == []

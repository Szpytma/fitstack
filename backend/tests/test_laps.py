"""`laps.is_structured` — telling a session from a run.

Getting this wrong is expensive in both directions. A steady run read as
structured drops out of the efficiency factor that drives adaptation; a real
interval session read as steady has its threshold taken from an average that
includes the jog backs.
"""

from __future__ import annotations

from conftest import laps_fast_finish, laps_reps, laps_steady

from app import laps


def test_steady_run_is_not_structured():
    assert laps.is_structured(laps_steady()) is False


def test_interval_session_is_structured():
    assert laps.is_structured(laps_reps()) is True


def test_fast_finish_is_not_structured():
    """One sustained quick block is a tempo finish, not reps."""
    assert laps.is_structured(laps_fast_finish()) is False


def test_too_few_laps_is_not_structured():
    assert laps.is_structured(laps_reps(reps=1)) is False
    assert laps.is_structured([]) is False
    assert laps.is_structured(None) is False


def test_work_effort_reads_the_reps_not_the_recoveries():
    """10 x 1 km should come back as ~10 km at rep pace, jog backs excluded."""
    effort = laps.work_effort(laps_reps())
    assert effort is not None
    dist_m, dur_s = effort
    assert 9000 <= dist_m <= 11000
    # 240 s per rep before the rep discount; the jog backs would drag this well
    # past 300 s/km if they leaked in.
    assert dur_s / (dist_m / 1000.0) < 280

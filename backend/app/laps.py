"""Reading a structured session for what it was, not for its average.

A session of 5 km warmup, 10 x 1 km at target and 2 km easy back has a
whole-activity average pace that belongs to none of those three things, and an
average heart rate that lands wherever the ratio of work to jogging puts it.
Two parts of FitStack were reading exactly that average and drawing conclusions
from it:

  * `adapt.efficiency_factor` — an interval session usually averages 80-85% of
    max HR, which passes the aerobic window, so it joined the weekly median with
    a number that blends reps and recoveries.
  * `planner.threshold_from_activities` — Riegel over the whole activity, so the
    best threshold measurement of the athlete's week projected as a slow 10K and
    lost to an ordinary steady run.

Garmin already records the laps; nothing here calls out to it. These are pure
functions over the lap list, and `history.attach_laps` is the one place that
fetches them.
"""

from __future__ import annotations

from typing import Any

#: A lap shorter than this is a recovery jog or a stray split, not a rep.
MIN_LAP_M = 200.0
#: Laps this much slower than the fastest are not part of the same effort.
WORK_TOLERANCE = 0.06
#: How much quicker the reps must be than the running between them. Kilometre
#: splits on an ordinary run vary by more than people expect — hills, crossings,
#: a slow first kilometre — so this is a gap, not a wobble.
REP_ADVANTAGE = 0.15
#: A structured session alternates: reps separated by recoveries. This many
#: separate fast sections, at least, or it is a steady run with a fast finish.
MIN_REP_BLOCKS = 3
#: Fewer laps than this is not a session with a structure to read.
MIN_LAPS = 5
#: Aggregate work below this says too little to read a threshold from.
MIN_WORK_M = 3000.0
#: Reps run with recovery are quicker than the same distance run continuously.
#: The aggregate is discounted by this before it is treated as a single effort.
REP_DISCOUNT = 0.96


def _speed(lap: dict[str, Any]) -> float | None:
    dist, dur = lap.get("distance_m"), lap.get("duration_s")
    if not dist or not dur or float(dur) <= 0 or float(dist) < MIN_LAP_M:
        return None
    return float(dist) / float(dur)


def _fast_flags(speeds: list[float]) -> list[bool]:
    fastest = max(speeds)
    return [s >= fastest * (1.0 - WORK_TOLERANCE) for s in speeds]


def _blocks(flags: list[bool]) -> int:
    """How many separate runs of True there are — reps, if they are reps."""
    return sum(1 for i, f in enumerate(flags) if f and (i == 0 or not flags[i - 1]))


def is_structured(laps: list[dict[str, Any]] | None) -> bool:
    """True when the laps show reps with recoveries between them.

    Spread alone is not enough, and getting this wrong is expensive in both
    directions: call a steady run structured and it drops out of the efficiency
    factor that drives adaptation; miss a real session and its threshold is read
    from an average that includes the jog backs.

    A recreational runner's kilometre splits swing 15-20% on an ordinary run —
    hills, road crossings, a first kilometre run cold — so what marks a session
    is not variation but *alternation*: several separate fast sections, each
    clearly quicker than the running around them.
    """
    speeds = [s for lap in (laps or []) if (s := _speed(lap)) is not None]
    if len(speeds) < MIN_LAPS:
        return False

    flags = _fast_flags(speeds)
    fast = [s for s, f in zip(speeds, flags) if f]
    slow = [s for s, f in zip(speeds, flags) if not f]
    if len(fast) < 3 or not slow:
        return False
    if _blocks(flags) < MIN_REP_BLOCKS:
        return False  # one fast block is a tempo finish, not an interval session

    rep_speed = sum(fast) / len(fast)
    between = sorted(slow)[len(slow) // 2]
    return between > 0 and (rep_speed - between) / rep_speed > REP_ADVANTAGE


def work_effort(laps: list[dict[str, Any]] | None) -> tuple[float, float] | None:
    """The reps alone, as one (distance_m, duration_s) effort.

    Every lap within `WORK_TOLERANCE` of the fastest is taken to be part of the
    same set — the ten kilometre reps, not the warmup, the jog backs or the way
    home. Returns None when what is left is too short to read anything from.
    """
    measured = [
        (float(lap["distance_m"]), float(lap["duration_s"]), s)
        for lap in (laps or [])
        if (s := _speed(lap)) is not None
    ]
    if not measured:
        return None
    fastest = max(s for *_, s in measured)
    work = [(d, t) for d, t, s in measured if s >= fastest * (1.0 - WORK_TOLERANCE)]
    dist = sum(d for d, _ in work)
    dur = sum(t for _, t in work)
    if dist < MIN_WORK_M or dur <= 0:
        return None
    return dist, dur


def continuous_equivalent(laps: list[dict[str, Any]] | None) -> tuple[float, float] | None:
    """The reps as the continuous effort they are worth, for Riegel to project.

    Ten kilometre reps off a short jog are quicker than ten kilometres run
    straight through, so the aggregate is slowed by `REP_DISCOUNT` before it is
    treated as one effort. The discount is deliberately conservative: reading a
    session as faster than it was puts every pace band in the plan out.
    """
    effort = work_effort(laps)
    if effort is None:
        return None
    dist, dur = effort
    return dist, dur / REP_DISCOUNT

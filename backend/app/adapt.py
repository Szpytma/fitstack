"""Deterministic week-to-week adaptation for a rolling plan.

Garmin Coach hands out one week, watches how it went, then proposes the next.
This is that loop, with the decision written down rather than inferred by a model:
given what the athlete actually ran and how hard it felt to their heart, decide
whether the next week advances, holds, or steps back.

Everything here is a pure function of (plan, activities). No I/O, no LLM. That is
deliberate — six weeks into a block you must be able to answer "why was week 5
lighter?" and get the same answer every time. An LLM belongs on the exceptions the
data cannot show (illness, travel, a niggle), not on the numbers.

**Conservative by design.** Every rule needs the same signal in *two consecutive*
weeks before it fires. With four runs a week, one week is too small a sample, and a
plan that lurches every seven days has stopped being a plan.

Effort is read through **efficiency factor** — metres per minute per heartbeat. Run
the same easy pace at a higher heart rate than a fortnight ago and you are not
absorbing the work. It is a real signal (this account's EF ran 0.80 in June, 0.91
by late July, back to 0.81 after a four-week gap) but a noisy one, so:

  * only aerobic runs count — a 5K time trial has a high EF and means nothing here
  * a week is represented by its *median*, never a single run
  * the comparison is against a baseline median, not the week before
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app import laps

log = logging.getLogger(__name__)

# --- thresholds -------------------------------------------------------------
# Conservative: each needs to hold for CONSECUTIVE weeks running before it acts.

CONSECUTIVE = 2
#: Below this share of the week's planned km, the week did not happen as asked.
SHORT_WEEK = 0.70
#: Above this, the athlete overreached; do not let the ramp compound it.
BIG_WEEK = 1.30
#: EF this far under baseline means the same work is costing more.
EF_DECLINE = 0.95
#: Aerobic window as a share of max HR. Outside it a run says nothing about
#: aerobic efficiency — too easy to be informative, or too hard to compare.
AEROBIC_LO, AEROBIC_HI = 0.60, 0.85
#: Volume multiplier when the athlete has stopped running altogether.
STEP_BACK = 0.75
#: Volume multiplier when they are doing the work but struggling with it.
STRUGGLE_HOLD = 0.90
MIN_KM = 3.0


@dataclass
class WeekReport:
    """What one plan week asked for, and what actually happened."""

    week_number: int
    start: date
    end: date
    planned_km: float
    actual_km: float = 0.0
    runs_done: int = 0
    runs_planned: int = 0
    ef_median: float | None = None
    ef_samples: int = 0

    @property
    def ratio(self) -> float | None:
        return round(self.actual_km / self.planned_km, 2) if self.planned_km else None

    def as_json(self) -> dict[str, Any]:
        return {
            "week_number": self.week_number,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "planned_km": round(self.planned_km, 1),
            "actual_km": round(self.actual_km, 1),
            "ratio": self.ratio,
            "runs_done": self.runs_done,
            "runs_planned": self.runs_planned,
            "ef_median": self.ef_median,
            "ef_samples": self.ef_samples,
        }


@dataclass
class Decision:
    """The adjustment for one upcoming week, and why."""

    week_number: int
    action: str  # "advance" | "hold" | "step_back"
    scale: float
    reasons: list[str] = field(default_factory=list)
    looked_at: list[dict[str, Any]] = field(default_factory=list)
    ef_baseline: float | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "week_number": self.week_number,
            "action": self.action,
            "scale": round(self.scale, 3),
            "reasons": self.reasons,
            "looked_at": self.looked_at,
            "ef_baseline": self.ef_baseline,
        }


def _day_of(activity: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(activity.get("start_local") or "")[:10])
    except ValueError:
        return None


def efficiency_factor(activity: dict[str, Any], max_hr: int | None) -> float | None:
    """Metres per minute per heartbeat, or None if the run cannot be compared.

    Rejects anything outside the aerobic window: a hard time trial posts a high EF
    because speed rose faster than heart rate, which says nothing about whether
    easy running is getting cheaper.
    """
    if "run" not in (activity.get("type") or "").lower():
        return None
    if laps.is_structured(activity.get("laps")):
        # A session of reps and jog backs averages to a pace and a heart rate
        # that belong to neither. Its average often lands inside the aerobic
        # window, so the window alone will not keep it out.
        return None
    dist = activity.get("distance_m")
    hr = activity.get("avg_hr")
    mps = activity.get("avg_speed_mps")
    if not dist or not hr or not mps or dist < MIN_KM * 1000:
        return None
    if max_hr:
        share = float(hr) / max_hr
        if not AEROBIC_LO <= share <= AEROBIC_HI:
            return None
    return round((float(mps) * 60.0) / float(hr), 3)


def _ef_median(activities: list[dict[str, Any]], max_hr: int | None) -> tuple[float | None, int]:
    vals = [ef for a in activities if (ef := efficiency_factor(a, max_hr)) is not None]
    if not vals:
        return None, 0
    return round(statistics.median(vals), 3), len(vals)


def ef_baseline(
    activities: list[dict[str, Any]],
    before: date,
    max_hr: int | None,
    weeks: int = 4,
) -> tuple[float | None, int]:
    """Median EF over the weeks leading up to `before` — what "normal" costs.

    Compared against, never recomputed from the plan itself: if the baseline drifted
    down with the athlete, a slow decline would never register.
    """
    window = [
        a
        for a in activities
        if (d := _day_of(a)) is not None and (before - d).days in range(0, weeks * 7)
    ]
    return _ef_median(window, max_hr)


def report_week(
    week: dict[str, Any],
    activities: list[dict[str, Any]],
    max_hr: int | None,
) -> WeekReport:
    """Roll one plan week up against the runs actually recorded inside it."""
    start = date.fromisoformat(week["start"])
    end = date.fromisoformat(week["end"])
    inside = [
        a
        for a in activities
        if (d := _day_of(a)) is not None
        and start <= d <= end
        and "run" in (a.get("type") or "").lower()
    ]
    km = sum(float(a["distance_m"]) / 1000.0 for a in inside if a.get("distance_m"))
    ef, n = _ef_median(inside, max_hr)
    return WeekReport(
        week_number=int(week["index"]),
        start=start,
        end=end,
        planned_km=float(week["planned_km"]),
        actual_km=round(km, 1),
        runs_done=len(inside),
        runs_planned=len(week.get("sessions") or []),
        ef_median=ef,
        ef_samples=n,
    )


def completed_weeks(
    full_plan: dict[str, Any],
    before_week: int,
    activities: list[dict[str, Any]],
    max_hr: int | None,
    today: date,
    limit: int = CONSECUTIVE,
) -> list[WeekReport]:
    """The most recent finished weeks before `before_week`, newest first."""
    out: list[WeekReport] = []
    for w in reversed(full_plan.get("weeks") or []):
        n = int(w["index"])
        if n >= before_week:
            continue
        if date.fromisoformat(w["end"]) > today:
            continue  # still to come — not evidence yet
        out.append(report_week(w, activities, max_hr))
        if len(out) >= limit:
            break
    return out


def _hold_scale(
    full_plan: dict[str, Any], week_number: int, prev_planned: float
) -> float:
    """Factor that levels this week at the previous one — but never lifts it.

    Without the clamp a "hold" lands *above* the plan whenever the upcoming week is
    already lighter than the one before it: a down week or any taper week asks for
    less by design, and levelling it at the previous week would undo that.
    """
    this_week = next(
        (w for w in full_plan.get("weeks") or [] if int(w["index"]) == week_number),
        None,
    )
    planned = float(this_week["planned_km"]) if this_week else 0.0
    if not planned:
        return 1.0
    return round(min(1.0, prev_planned / planned), 3)


def decide(
    full_plan: dict[str, Any],
    week_number: int,
    activities: list[dict[str, Any]],
    max_hr: int | None = None,
    today: date | None = None,
    plan_start: date | None = None,
) -> Decision:
    """Whether the upcoming week advances, holds, or steps back.

    Holding means serving the *previous* week's volume again rather than climbing
    the ramp. The calendar never moves: weeks are anchored backwards from the race
    date, so inserting one would have to steal from the peak phase. Re-levelling the
    week keeps the taper where it belongs.
    """
    today = today or date.today()
    recent = completed_weeks(full_plan, week_number, activities, max_hr, today)
    base, base_n = ef_baseline(activities, plan_start or today, max_hr)

    d = Decision(
        week_number=week_number,
        action="advance",
        scale=1.0,
        looked_at=[r.as_json() for r in recent],
        ef_baseline=base,
    )

    if len(recent) < CONSECUTIVE:
        d.reasons.append(
            f"Only {len(recent)} finished week(s) to go on — advancing as planned "
            f"until there are {CONSECUTIVE}."
        )
        return d

    window = recent[:CONSECUTIVE]

    # Nothing at all, twice over — the ramp is fiction at this point.
    if all(r.runs_done == 0 for r in window):
        d.action = "step_back"
        d.scale = STEP_BACK
        d.reasons.append(
            f"No runs recorded in the last {CONSECUTIVE} weeks — stepping back to "
            f"{int(STEP_BACK * 100)}% rather than resuming the ramp."
        )
        return d

    short = [r for r in window if (r.ratio or 0) < SHORT_WEEK]
    if len(short) == CONSECUTIVE:
        prev = window[0]
        # Level at what the last week asked for, never above what this one already
        # asks: a down week or a taper week is lighter on purpose.
        d.scale = _hold_scale(full_plan, week_number, prev.planned_km)
        d.action = "hold"
        d.reasons.append(
            f"{CONSECUTIVE} weeks running below {int(SHORT_WEEK * 100)}% of plan ("
            + ", ".join(
                f"week {r.week_number}: {r.actual_km:g}/{r.planned_km:g} km" for r in window
            )
            + ") — holding volume instead of climbing."
        )
        return d

    big = [r for r in window if (r.ratio or 0) > BIG_WEEK]
    if len(big) == CONSECUTIVE:
        d.action = "hold"
        d.scale = _hold_scale(full_plan, week_number, window[0].planned_km)
        d.reasons.append(
            f"{CONSECUTIVE} weeks well over plan — holding this one so the extra does "
            "not compound."
        )
        return d

    # Doing the work, but it is costing more than it used to.
    if base and base_n >= 3:
        declining = [
            r
            for r in window
            if r.ef_median is not None
            and r.ef_samples >= 1
            and r.ef_median / base < EF_DECLINE
        ]
        if len(declining) == CONSECUTIVE:
            d.action = "hold"
            d.scale = STRUGGLE_HOLD
            worst = min(r.ef_median for r in declining if r.ef_median)
            d.reasons.append(
                f"Efficiency down {CONSECUTIVE} weeks running ({worst:.2f} vs {base:.2f} "
                f"baseline) — same paces are costing more heartbeats, so volume holds "
                f"at {int(STRUGGLE_HOLD * 100)}%."
            )
            return d

    d.reasons.append("Last weeks landed as planned — advancing.")
    return d


def scales_through(
    full_plan: dict[str, Any],
    up_to_week: int,
    activities: list[dict[str, Any]],
    max_hr: int | None = None,
    today: date | None = None,
    plan_start: date | None = None,
) -> tuple[dict[int, float], Decision | None]:
    """Adjustment factors for every week up to and including `up_to_week`.

    Earlier weeks' decisions are kept so the block stays consistent when you page
    back through it — the week you were given in October does not change because
    November went badly.
    """
    scales: dict[int, float] = {}
    latest: Decision | None = None
    for n in range(2, up_to_week + 1):
        dec = decide(full_plan, n, activities, max_hr, today, plan_start)
        if dec.scale != 1.0:
            scales[n] = dec.scale
        if n == up_to_week:
            latest = dec
    return scales, latest

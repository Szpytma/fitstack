"""The one piece of state FitStack keeps: which plan is currently running.

Everything else in the app is derived from Garmin on demand. A rolling weekly
plan cannot be, because "which week am I in" is not recoverable from history.
Regenerating from today would restart the periodisation every time: `total_weeks`
shrinks by one each week, so `phase_for(0, total, taper)` returns "base" forever
and `volume_curve` restarts its four-week cycle before a down week ever lands.

So two things are pinned at plan creation and never move:

    start_date        keeps `total_weeks` fixed, so the phase arc actually advances
    anchor_weekly_km  keeps the volume ramp from drifting with a sick or heavy week

Paces are deliberately *not* pinned. `threshold_from_activities` re-reads them on
every rebuild, which is the entire point of planning one week at a time — the
plan tracks your fitness while its shape stays periodised.

`build_plan` needs no changes for any of this: it already anchors weeks backwards
from the race date, so replaying it with the original `start_date` reproduces the
same calendar weeks with the same phases.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app import adapt
from app.base_plan import BaseInput, build_base_plan
from app.config import settings
from app.planner import PlanInput, block_start, block_weeks, build_plan

log = logging.getLogger(__name__)

STATE_FILENAME = "active_plan.json"


class NoActivePlan(RuntimeError):
    """Raised when a rolling-week call is made with no plan started."""


@dataclass
class ActivePlan:
    """The immutable anchor for a rolling plan, plus the inputs to replay it."""

    race_km: float
    race_date: date
    start_date: date
    anchor_weekly_km: float
    runs_per_week: int = 4
    long_run_day: str = "Sunday"
    goal_time_s: float | None = None
    race_name: str | None = None
    target_mode: str = "pace"
    #: "race" builds towards a date; "base" is an open-ended zone 2 block whose
    #: progression is in minutes. They are different planners, not a flag.
    mode: str = "race"
    weeks: int = 12
    weekly_minutes: float | None = None
    #: The block exactly as generated on day one. Replay reproduces it, but only
    #: while the planner is unchanged — keeping it makes "what did this plan
    #: originally say" answerable, and survives a planner tweak mid-block.
    original: dict[str, Any] | None = None

    def to_input(self) -> PlanInput:
        return PlanInput(
            race_km=self.race_km,
            race_date=self.race_date,
            runs_per_week=self.runs_per_week,
            long_run_day=self.long_run_day,
            weekly_km=self.anchor_weekly_km,
            goal_time_s=self.goal_time_s,
            race_name=self.race_name,
            start_date=self.start_date,
            target_mode=self.target_mode,
        )

    def as_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["race_date"] = self.race_date.isoformat()
        d["start_date"] = self.start_date.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> ActivePlan:
        return cls(
            race_km=float(d["race_km"]),
            race_date=date.fromisoformat(d["race_date"]),
            start_date=date.fromisoformat(d["start_date"]),
            anchor_weekly_km=float(d["anchor_weekly_km"]),
            runs_per_week=int(d.get("runs_per_week", 4)),
            long_run_day=d.get("long_run_day") or "Sunday",
            goal_time_s=d.get("goal_time_s"),
            race_name=d.get("race_name"),
            target_mode=d.get("target_mode") or "pace",
            mode=d.get("mode") or "race",
            weeks=int(d.get("weeks") or 12),
            weekly_minutes=d.get("weekly_minutes"),
            original=d.get("original"),
        )


def _state_path() -> Path:
    return settings.state_dir / STATE_FILENAME


def save(plan: ActivePlan) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.as_json(), indent=2), encoding="utf-8")
    log.info("active plan saved to %s", path)


def load() -> ActivePlan | None:
    path = _state_path()
    if not path.exists():
        return None
    try:
        return ActivePlan.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, KeyError, OSError) as exc:
        # A corrupt state file must not brick the app — surface it and let the
        # caller start a fresh plan rather than failing every request forever.
        log.warning("active plan at %s is unreadable (%s); ignoring", path, exc)
        return None


def clear() -> bool:
    path = _state_path()
    if not path.exists():
        return False
    path.unlink()
    log.info("active plan cleared from %s", path)
    return True


def require() -> ActivePlan:
    plan = load()
    if plan is None:
        raise NoActivePlan(
            "No training plan is running. Start one first with the race distance "
            "and date, then ask for each week as it comes."
        )
    return plan


def upcoming_week_start(today: date | None = None, offset: int = 0) -> date:
    """The Monday on or after `today`, shifted by `offset` weeks.

    Asking the evening of a Sunday long run returns tomorrow's week, which is the
    cadence this is built for. Asking midweek returns the *next* Monday; pass
    offset=-1 to get the week already in progress.
    """
    today = today or date.today()
    monday = today + timedelta(days=(7 - today.weekday()) % 7)
    return monday + timedelta(weeks=offset)


def anchor_from_plan(plan: dict[str, Any]) -> float:
    """The resolved week-one volume, which is what pins the ramp on replay.

    `build_plan` resolves start volume from stated km, observed history or a
    floor, and `volume_curve` emits it unchanged as the first week — so the first
    week's target *is* the resolved start, with no planner change needed.

    Read `planned_km` (the curve's target), not `volume_km` (the sum of the
    week's rounded session distances). Feeding the latter back in would replay
    the block from a slightly different start than the one it was built from.
    """
    weeks = plan.get("weeks") or []
    if not weeks:
        raise ValueError("plan has no weeks to anchor to")
    return float(weeks[0]["planned_km"])


def anchor_minutes_from_plan(plan: dict[str, Any]) -> float | None:
    """Week-one minutes — the base block's equivalent of the volume anchor."""
    weeks = plan.get("weeks") or []
    if not weeks:
        return None
    return float(weeks[0].get("planned_minutes") or 0) or None


def rebuild(
    plan: ActivePlan,
    activities: list[dict[str, Any]] | None = None,
    hr_zones: dict[str, Any] | None = None,
    week_scale: dict[int, float] | None = None,
) -> dict[str, Any]:
    """Replay the full block from the pinned anchor, with today's fitness.

    `week_scale` carries the adaptation decisions back in, so the sessions are
    shaped by the planner at the adjusted volume rather than scaled afterwards.
    """
    if plan.mode == "base":
        return build_base_plan(
            BaseInput(
                weeks=plan.weeks,
                runs_per_week=plan.runs_per_week,
                long_run_day=plan.long_run_day,
                weekly_minutes=plan.weekly_minutes,
                start_date=plan.start_date,
                plan_name=plan.race_name,
                week_scale=week_scale,
            ),
            activities or [],
            hr_zones,
        )
    inp = plan.to_input()
    if week_scale:
        inp.week_scale = week_scale
    return build_plan(inp, activities or [], hr_zones)


def lead_in_weeks(plan: ActivePlan) -> int:
    """Weeks between the plan starting and the race block opening.

    Zero for any race inside the block cap — the usual case. Positive when the
    race is further out than `build_plan` will lay out in one go, because the
    block is anchored backwards from race week and therefore opens later than
    today.
    """
    opens = block_start(plan.start_date, plan.race_date)
    first = upcoming_week_start(plan.start_date)
    return max(0, (opens - first).days // 7)


def lead_in_view(
    plan: ActivePlan,
    activities: list[dict[str, Any]],
    hr_zones: dict[str, Any] | None,
    week_start: date,
) -> dict[str, Any]:
    """A lead-in week: aerobic base, before the race block opens.

    The race block covers the final `MAX_BLOCK_WEEKS`; a race further out leaves
    weeks in front of it that used to 400 with "no plan week starts on …". They
    are not an error — they are exactly the weeks in which to build aerobic base,
    which is what `base_plan` exists for. So the lead-in is a real base block:
    zone 2, minutes in and pace out, anchored on the same start date so it
    replays identically week to week.
    """
    weeks = lead_in_weeks(plan)
    if weeks <= 0:
        raise ValueError("this plan has no lead-in")

    opens = block_start(plan.start_date, plan.race_date)
    base = build_base_plan(
        BaseInput(
            weeks=weeks,
            runs_per_week=plan.runs_per_week,
            long_run_day=plan.long_run_day,
            start_date=upcoming_week_start(plan.start_date),
            plan_name=f"Base — lead-in to {plan.race_name or 'the race'}",
        ),
        activities,
        hr_zones,
    )
    view = week_view(plan, base, week_start, activities)
    # week_view reads the race from the plan it was handed, which here is the
    # base block. The race is still the point of the lead-in, so say so.
    view["race_name"] = plan.race_name
    view["race_km"] = plan.race_km
    view["race_date"] = plan.race_date.isoformat()
    view["lead_in"] = True
    view["race_block_opens"] = opens.isoformat()
    view["warnings"] = [
        f"Lead-in week {view['week_number']} of {weeks}. The {plan.race_km:g} km "
        f"block opens on {opens.isoformat()}; until then this is aerobic base — "
        "heart rate is the prescription and pace is whatever it produces.",
        *view.get("warnings", []),
    ]
    return view


def adapted_view(
    plan: ActivePlan,
    activities: list[dict[str, Any]],
    hr_zones: dict[str, Any] | None,
    week_start: date,
    today: date | None = None,
) -> dict[str, Any]:
    """One week after adaptation, carrying the decision that shaped it.

    Two passes on purpose. The first builds the block *unadjusted* — that is the
    yardstick the decisions are measured against, so a held week never becomes the
    new normal that the next hold is judged from. The second rebuilds with the
    accumulated scales so the planner shapes the sessions itself.
    """
    today = today or date.today()
    max_hr = (hr_zones or {}).get("max_hr")

    original = rebuild(plan, activities, hr_zones)
    target = select_week(original, week_start)
    if target is None:
        weeks = original.get("weeks") or []
        first = weeks[0]["start"] if weeks else "?"
        last = weeks[-1]["end"] if weeks else "?"
        # Before the block opens is lead-in, not "outside the plan".
        if plan.mode != "base" and weeks and week_start < date.fromisoformat(first):
            return lead_in_view(plan, activities, hr_zones, week_start)
        raise ValueError(
            f"No plan week starts on {week_start.isoformat()} — this block runs "
            f"{first} to {last}. The race may already have passed."
        )

    number = int(target["index"])
    scales, decision = adapt.scales_through(
        original, number, activities, max_hr, today, plan.start_date
    )
    adjusted = rebuild(plan, activities, hr_zones, scales) if scales else original

    view = week_view(plan, adjusted, week_start, activities)
    view["decision"] = decision.as_json() if decision else None
    view["original_planned_km"] = round(float(target["planned_km"]), 1)
    return view


def select_week(full_plan: dict[str, Any], week_start: date) -> dict[str, Any] | None:
    """The week beginning on `week_start`, or None if it falls outside the plan."""
    iso = week_start.isoformat()
    for week in full_plan.get("weeks") or []:
        if week.get("start") == iso:
            return week
    return None


def _runs_between(
    activities: list[dict[str, Any]] | None, start: date, end: date
) -> tuple[float, int]:
    """Total km and number of runs actually recorded in [start, end]."""
    km, n = 0.0, 0
    for a in activities or []:
        if "run" not in (a.get("type") or "").lower():
            continue
        try:
            day = date.fromisoformat(str(a.get("start_local") or "")[:10])
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        dist = a.get("distance_m")
        if dist is None:
            continue
        km += float(dist) / 1000.0
        n += 1
    return round(km, 1), n


def compliance(
    full_plan: dict[str, Any],
    week_number: int,
    activities: list[dict[str, Any]] | None,
    today: date | None = None,
) -> dict[str, Any] | None:
    """How the *previous* week actually went, against what it asked for.

    Reported, not acted on: the volume ramp stays anchored either way. Whether a
    missed week should hold the progression is a coaching decision, not something
    to infer silently — see the `ratio` and decide.

    None while that week is still running, or before there is a previous week.
    """
    today = today or date.today()
    prev = next(
        (w for w in full_plan.get("weeks") or [] if int(w["index"]) == week_number - 1),
        None,
    )
    if prev is None:
        return None
    end = date.fromisoformat(prev["end"])
    if end >= today:
        return None  # still in progress — nothing to judge yet

    planned = float(prev["planned_km"])
    actual_km, runs = _runs_between(
        activities, date.fromisoformat(prev["start"]), end
    )
    return {
        "week_number": int(prev["index"]),
        "start": prev["start"],
        "end": prev["end"],
        "planned_km": round(planned, 1),
        "actual_km": actual_km,
        "ratio": round(actual_km / planned, 2) if planned else None,
        "runs_done": runs,
        "runs_planned": len(prev.get("sessions") or []),
    }


def week_view(
    plan: ActivePlan,
    full_plan: dict[str, Any],
    week_start: date,
    activities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One week, wrapped with the context needed to act on it.

    Carries `basis` so the caller can see which run the paces came from, and the
    position in the block so "week 4 of 11, build phase" is answerable without
    re-deriving it.
    """
    week = select_week(full_plan, week_start)
    weeks_total = int(full_plan.get("weeks_total") or 0)

    if week is None:
        weeks = full_plan.get("weeks") or []
        first = weeks[0]["start"] if weeks else "?"
        last = weeks[-1]["end"] if weeks else "?"
        raise ValueError(
            f"No plan week starts on {week_start.isoformat()} — this block runs "
            f"{first} to {last}. The race may already have passed."
        )

    # `build_plan` emits `index` 1-based (planner.py:860), unlike the 0-based
    # week_idx it uses internally for phase_for.
    number = int(week["index"])
    remaining = weeks_total - number
    return {
        "race_name": full_plan.get("race_name"),
        "race_km": full_plan.get("race_km"),
        "race_date": full_plan.get("race_date"),
        "week_number": number,
        "weeks_total": weeks_total,
        "weeks_remaining_after_this": max(0, remaining),
        "target_mode": full_plan.get("target_mode", "pace"),
        "basis": full_plan.get("basis"),
        "hr_basis": full_plan.get("hr_basis"),
        "warnings": full_plan.get("warnings") or [],
        "last_week": compliance(full_plan, number, activities),
        "week": week,
    }


def status(plan: ActivePlan, today: date | None = None) -> dict[str, Any]:
    """Where the athlete is in the block, without rebuilding the whole plan."""
    today = today or date.today()
    days_to_race = (plan.race_date - today).days
    return {
        "race_name": plan.race_name,
        "race_km": plan.race_km,
        "race_date": plan.race_date.isoformat(),
        "started": plan.start_date.isoformat(),
        "days_to_race": days_to_race,
        "weeks_to_race": days_to_race // 7,
        "runs_per_week": plan.runs_per_week,
        "long_run_day": plan.long_run_day,
        "target_mode": plan.target_mode,
        "anchor_weekly_km": plan.anchor_weekly_km,
        "next_week_starts": upcoming_week_start(today).isoformat(),
        "block_weeks": block_weeks(plan.start_date, plan.race_date),
        "race_block_opens": block_start(plan.start_date, plan.race_date).isoformat(),
        "lead_in_weeks": lead_in_weeks(plan) if plan.mode != "base" else 0,
    }

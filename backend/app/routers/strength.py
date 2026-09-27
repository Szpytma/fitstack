from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import active_plan
from app.deps import get_garmin
from app.providers.base import FitnessProvider
from app.schemas.strength import (
    StrengthApplyRequest,
    StrengthApplyResult,
    StrengthPlan,
    StrengthWeekView,
)
from app.strength_plan import StrengthInput, build_strength_plan

log = logging.getLogger(__name__)

router = APIRouter(prefix="/strength", tags=["strength"])

DEFAULT_DAYS = ["Wednesday", "Friday", "Sunday"]


class StrengthConfig(BaseModel):
    days: list[str] = Field(default_factory=lambda: list(DEFAULT_DAYS))
    weeks: int | None = Field(None, ge=1, le=24)
    long_run_day: str | None = None


def _plan_for(plan: active_plan.ActivePlan, days: list[str] | None = None) -> dict:
    """Build the strength block off the running plan's own anchor.

    Same `start_date` and `weeks` as the running block by construction — that is
    why `strength_days` lives on `ActivePlan` rather than in its own file.
    """
    return build_strength_plan(
        StrengthInput(
            weeks=plan.weeks,
            days=days or plan.strength_days or list(DEFAULT_DAYS),
            long_run_day=plan.long_run_day,
            start_date=plan.start_date,
            plan_name=f"{plan.race_name or 'Plan'} — strength",
        )
    )


@router.post(
    "/preview",
    response_model=StrengthPlan,
    summary="Build a strength block (writes nothing)",
)
def preview(cfg: StrengthConfig) -> StrengthPlan:
    plan = active_plan.load()
    try:
        return StrengthPlan(
            **build_strength_plan(
                StrengthInput(
                    weeks=cfg.weeks or (plan.weeks if plan else 14),
                    days=cfg.days,
                    long_run_day=cfg.long_run_day
                    or (plan.long_run_day if plan else "Sunday"),
                    start_date=plan.start_date if plan else None,
                    plan_name="Strength",
                )
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/enable",
    response_model=StrengthWeekView,
    summary="Attach a strength block to the running plan and return this week",
)
def enable(cfg: StrengthConfig) -> StrengthWeekView:
    try:
        plan = active_plan.require()
    except active_plan.NoActivePlan as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    plan.strength_days = cfg.days
    active_plan.save(plan)
    return _week_view(plan, 0)


@router.delete("/", summary="Detach the strength block (leaves Garmin untouched)")
def disable() -> dict[str, bool]:
    plan = active_plan.load()
    if plan is None or not plan.strength_days:
        return {"cleared": False}
    plan.strength_days = None
    active_plan.save(plan)
    return {"cleared": True}


def _week_view(plan: active_plan.ActivePlan, offset: int) -> StrengthWeekView:
    full = _plan_for(plan)
    target = active_plan.upcoming_week_start(offset=offset).isoformat()
    week = next((w for w in full["weeks"] if w["start"] == target), None)
    if week is None:
        first = full["weeks"][0]["start"] if full["weeks"] else "?"
        last = full["weeks"][-1]["end"] if full["weeks"] else "?"
        raise HTTPException(
            status_code=400,
            detail=f"No strength week starts on {target} — block runs {first} to {last}.",
        )
    return StrengthWeekView(
        plan_name=full["plan_name"],
        week_number=int(week["index"]),
        weeks_total=int(full["weeks_total"]),
        days=full["days"],
        notes=full["notes"],
        week=week,
    )


@router.get(
    "/week",
    response_model=StrengthWeekView,
    summary="The upcoming week of the strength block",
)
def week(offset: int = Query(0, ge=-4, le=20)) -> StrengthWeekView:
    plan = active_plan.load()
    if plan is None or not plan.strength_days:
        raise HTTPException(
            status_code=404,
            detail="No strength block attached. Enable one with POST /strength/enable.",
        )
    return _week_view(plan, offset)


@router.post(
    "/apply",
    response_model=StrengthApplyResult,
    summary="Create the strength workouts in Garmin and schedule them",
)
def apply(
    req: StrengthApplyRequest,
    provider: FitnessProvider = Depends(get_garmin),
) -> StrengthApplyResult:
    """One workout per scheduled date, same as the running path and for the same
    reason: the watch drops a template from the device once it is completed, and
    takes every other date sharing it. Strength weeks repeat shapes constantly, so
    sharing templates here would be worse than on the running side.
    """
    dates = sorted(d.date for d in req.sessions)
    removed = 0
    failures: list[str] = []

    if req.replace_existing and dates:
        span = (date.fromisoformat(dates[-1]) - date.today()).days + 1
        try:
            for w in provider.upcoming_workouts(days_ahead=max(1, span)):
                if w.get("sport") != "strength_training":
                    continue
                if not (dates[0] <= str(w.get("date")) <= dates[-1]):
                    continue
                provider.unschedule_workout(w["scheduled_id"])
                removed += 1
        except Exception as exc:  # pragma: no cover - upstream flakiness
            failures.append(f"could not clear existing strength workouts — {exc}")

    created = scheduled = 0
    workout_ids: list[int] = []
    for item in req.sessions:
        spec = item.spec.model_dump(exclude_none=True)
        try:
            result = provider.create_strength_workout(spec)
        except Exception as exc:
            failures.append(f"{item.date}: could not create '{spec.get('name')}' — {exc}")
            continue
        wid = result.get("workout_id")
        if wid is None:
            failures.append(f"{item.date}: Garmin returned no workout id")
            continue
        created += 1
        workout_ids.append(int(wid))
        try:
            provider.schedule_workout(wid, date.fromisoformat(item.date))
            scheduled += 1
        except Exception as exc:
            failures.append(f"{item.date}: could not schedule — {exc}")

    return StrengthApplyResult(
        created=created,
        scheduled=scheduled,
        removed=removed,
        failures=failures,
        workout_ids=workout_ids,
    )

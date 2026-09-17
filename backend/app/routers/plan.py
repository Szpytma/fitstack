from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app import active_plan, history
from app.deps import get_garmin
from app.base_plan import BaseInput, build_base_plan
from app.planner import PlanInput, build_plan
from app.providers.base import FitnessProvider
from app.schemas.plan import (
    PlanApplyRequest,
    PlanApplyResult,
    PlanRequest,
    PlanStatus,
    PlanWeekView,
    RacePlan,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])


@router.post(
    "/preview",
    response_model=RacePlan,
    summary="Generate a race training plan (computed locally, writes nothing)",
)
def preview(
    req: PlanRequest,
    provider: FitnessProvider = Depends(get_garmin),
) -> RacePlan:
    # Recent runs are the fitness basis when no goal time is supplied, and the
    # sanity check on the goal time when one is. Planning for someone else opts
    # out entirely — their paces must not be derived from this account's runs,
    # and must not borrow their heart rate zones either.
    activities, hr_zones = _plan_context(provider, req.target_mode, req.use_history)

    try:
        if req.mode == "base":
            plan = build_base_plan(
                BaseInput(
                    weeks=req.weeks,
                    runs_per_week=req.runs_per_week,
                    long_run_day=req.long_run_day,
                    weekly_minutes=req.weekly_minutes,
                    plan_name=req.race_name or "Aerobic base",
                ),
                activities,
                hr_zones,
            )
        else:
            if req.race_date is None:
                raise ValueError("A race plan needs a race date.")
            plan = build_plan(
                PlanInput(
                    race_km=req.race_km,
                    race_date=req.race_date,
                    runs_per_week=req.runs_per_week,
                    long_run_day=req.long_run_day,
                    weekly_km=req.weekly_km,
                    goal_time_s=req.goal_time_s,
                    race_name=req.race_name,
                    target_mode=req.target_mode,
                ),
                activities,
                hr_zones,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RacePlan(**plan)


def _plan_context(
    provider: FitnessProvider, target_mode: str, use_history: bool = True
) -> tuple[list[dict], dict | None]:
    activities: list[dict] = []
    if use_history:
        try:
            activities = provider.activities(limit=60)
        except Exception as exc:  # pragma: no cover - upstream flakiness
            log.warning("plan: could not read activities (%s); continuing without", exc)
        else:
            # Laps for the recent long-enough runs, so a structured session is
            # read from its reps rather than its average. See `laps.py`.
            history.attach_laps(provider, activities)

    # Always read zones, not just in HR mode: max HR is what makes the efficiency
    # factor comparable, and adaptation needs it whatever the targets are.
    hr_zones: dict | None = None
    if use_history:
        try:
            hr_zones = provider.heart_rate_zones()
        except Exception as exc:  # pragma: no cover - upstream flakiness
            log.warning("plan: could not read heart rate zones (%s); estimating", exc)
    return activities, hr_zones


@router.post(
    "/start",
    response_model=PlanWeekView,
    summary="Start a rolling plan and return its first week (writes nothing to Garmin)",
)
def start_rolling(
    req: PlanRequest,
    provider: FitnessProvider = Depends(get_garmin),
) -> PlanWeekView:
    """The whole block is computed; only the current week comes back.

    Replaces any plan already running. See active_plan.py for why the start date
    and week-one volume are pinned.
    """
    activities, hr_zones = _plan_context(provider, req.target_mode, req.use_history)
    today = date.today()

    try:
        if req.mode == "base":
            full = build_base_plan(
                BaseInput(
                    weeks=req.weeks,
                    runs_per_week=req.runs_per_week,
                    long_run_day=req.long_run_day,
                    weekly_minutes=req.weekly_minutes,
                    start_date=today,
                    plan_name=req.race_name or "Aerobic base",
                ),
                activities,
                hr_zones,
            )
        else:
            if req.race_date is None:
                raise ValueError("A race plan needs a race date.")
            full = build_plan(
                PlanInput(
                    race_km=req.race_km,
                    race_date=req.race_date,
                    runs_per_week=req.runs_per_week,
                    long_run_day=req.long_run_day,
                    weekly_km=req.weekly_km,
                    goal_time_s=req.goal_time_s,
                    race_name=req.race_name,
                    start_date=today,
                    target_mode=req.target_mode,
                ),
                activities,
                hr_zones,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    plan = active_plan.ActivePlan(
        race_km=req.race_km,
        race_date=req.race_date or date.fromisoformat(full["weeks"][-1]["end"]),
        start_date=today,
        anchor_weekly_km=active_plan.anchor_from_plan(full),
        runs_per_week=req.runs_per_week,
        long_run_day=req.long_run_day,
        goal_time_s=req.goal_time_s,
        race_name=req.race_name or full.get("race_name"),
        target_mode=full.get("target_mode", req.target_mode),
        mode=req.mode,
        weeks=req.weeks,
        weekly_minutes=(
            active_plan.anchor_minutes_from_plan(full)
            if req.mode == "base"
            else req.weekly_minutes
        ),
        original=full,
    )
    active_plan.save(plan)

    first_start = date.fromisoformat(full["weeks"][0]["start"])
    week_start = min(first_start, active_plan.upcoming_week_start(today))
    if active_plan.select_week(full, week_start) is None:
        week_start = first_start
    return PlanWeekView(**active_plan.week_view(plan, full, week_start, activities))


@router.get(
    "/week",
    response_model=PlanWeekView,
    summary="The next week of the running plan, rebuilt against current fitness",
)
def rolling_week(
    offset: int = Query(0, ge=-4, le=12, description="Weeks from the upcoming one"),
    provider: FitnessProvider = Depends(get_garmin),
) -> PlanWeekView:
    try:
        plan = active_plan.require()
    except active_plan.NoActivePlan as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    activities, hr_zones = _plan_context(provider, plan.target_mode)
    try:
        view = active_plan.adapted_view(
            plan,
            activities,
            hr_zones,
            active_plan.upcoming_week_start(offset=offset),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlanWeekView(**view)


@router.get(
    "/status",
    response_model=PlanStatus | None,
    summary="The running plan's race and position in the block, or null if none",
)
def rolling_status() -> PlanStatus | None:
    plan = active_plan.load()
    return PlanStatus(**active_plan.status(plan)) if plan else None


@router.delete(
    "/active",
    summary="Stop the rolling plan (leaves scheduled Garmin workouts alone)",
)
def end_rolling() -> dict[str, bool]:
    return {"cleared": active_plan.clear()}


@router.post(
    "/apply",
    response_model=PlanApplyResult,
    summary="Create the plan's workouts in Garmin and schedule them",
)
def apply(
    req: PlanApplyRequest,
    provider: FitnessProvider = Depends(get_garmin),
) -> PlanApplyResult:
    """One template per distinct session, scheduled on every date it recurs.

    A 12-week plan has ~50 sessions but only a handful of shapes, so uploading one
    template per calendar day would litter the account. Garmin is happy to hold one
    template on many dates — each scheduling call returns its own instance id.
    """
    templates: dict[str, int] = {}
    workout_ids: list[int] = []
    failures: list[str] = []
    scheduled = 0

    for item in req.sessions:
        spec = item.spec.model_dump(exclude_none=True)
        if not spec.get("steps"):
            continue  # race day and rest days carry no workout

        key = json.dumps(spec, sort_keys=True, default=str)
        workout_id = templates.get(key)

        if workout_id is None:
            try:
                created = provider.create_running_workout(spec)
            except Exception as exc:
                failures.append(f"{item.date}: could not create '{spec.get('name')}' — {exc}")
                continue
            workout_id = created.get("workout_id")
            if workout_id is None:
                failures.append(f"{item.date}: Garmin returned no workout id for '{spec.get('name')}'")
                continue
            templates[key] = workout_id
            workout_ids.append(workout_id)

        try:
            provider.schedule_workout(workout_id, item.date)
            scheduled += 1
        except Exception as exc:
            failures.append(f"{item.date}: could not schedule '{spec.get('name')}' — {exc}")

    return PlanApplyResult(
        templates_created=len(templates),
        scheduled=scheduled,
        failures=failures,
        workout_ids=workout_ids,
    )

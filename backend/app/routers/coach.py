from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.deps import get_garmin
from app.providers.base import FitnessProvider
from app.retarget import has_matching_target, shift_steps, spec_from_detail
from app.review import primary_target, review_session
from app.schemas.health import UpcomingWorkout

log = logging.getLogger(__name__)

router = APIRouter(prefix="/coach", tags=["coach"])


@router.get(
    "/upcoming",
    response_model=list[UpcomingWorkout],
    summary="Scheduled workouts from today through today+days_ahead",
)
def upcoming(
    days_ahead: int = Query(14, ge=1, le=60),
    provider: FitnessProvider = Depends(get_garmin),
) -> list[UpcomingWorkout]:
    return [UpcomingWorkout(**w) for w in provider.upcoming_workouts(days_ahead=days_ahead)]


@router.get("/workout/{workout_id}", summary="Full step structure for a workout template")
def workout(
    workout_id: int,
    provider: FitnessProvider = Depends(get_garmin),
) -> dict[str, Any]:
    return provider.workout_detail(workout_id)


class ShiftRequest(BaseModel):
    """Positive is harder in both units — higher bpm, faster pace."""

    delta: float = Field(..., description="bpm, or seconds per km")
    unit: Literal["bpm", "sec_per_km"] = "bpm"
    days_ahead: int = Field(60, ge=1, le=60)
    dry_run: bool = Field(True, description="Report what would change without writing")


class ShiftOutcome(BaseModel):
    workout_id: int
    name: str | None = None
    dates: list[str]
    status: Literal["updated", "would_update", "skipped", "failed"]
    reason: str | None = None


class ShiftResult(BaseModel):
    dry_run: bool
    updated: int
    skipped: int
    failed: int
    outcomes: list[ShiftOutcome]


@router.post(
    "/shift",
    response_model=ShiftResult,
    summary="Retarget every upcoming scheduled workout by a fixed amount",
)
def shift(
    req: ShiftRequest,
    provider: FitnessProvider = Depends(get_garmin),
) -> ShiftResult:
    """Update-in-place, so scheduled dates survive.

    One template can recur across many dates, so work per workout id rather than
    per calendar entry — otherwise a 12-week plan would be written a dozen times
    and shifted a dozen times over.
    """
    upcoming = provider.upcoming_workouts(days_ahead=req.days_ahead)

    by_workout: dict[int, list[str]] = {}
    for item in upcoming:
        wid = item.get("workout_id")
        if wid:
            by_workout.setdefault(int(wid), []).append(item.get("date") or "")

    outcomes: list[ShiftOutcome] = []
    for wid, dates in by_workout.items():
        try:
            detail = provider.workout_detail(wid)
        except Exception as exc:  # pragma: no cover - upstream flakiness
            outcomes.append(
                ShiftOutcome(workout_id=wid, dates=dates, status="failed", reason=str(exc))
            )
            continue

        name = detail.get("name")
        spec, blockers = spec_from_detail(detail)
        if spec is None:
            outcomes.append(
                ShiftOutcome(
                    workout_id=wid,
                    name=name,
                    dates=dates,
                    status="skipped",
                    reason="cannot be rebuilt safely: " + ", ".join(blockers),
                )
            )
            continue

        if not has_matching_target(spec["steps"], req.unit):
            outcomes.append(
                ShiftOutcome(
                    workout_id=wid,
                    name=name,
                    dates=dates,
                    status="skipped",
                    reason=f"no {'heart-rate' if req.unit == 'bpm' else 'pace'} target to shift",
                )
            )
            continue

        spec["steps"] = shift_steps(spec["steps"], req.delta, req.unit)

        if req.dry_run:
            outcomes.append(
                ShiftOutcome(workout_id=wid, name=name, dates=dates, status="would_update")
            )
            continue

        try:
            provider.update_running_workout(wid, spec)
            outcomes.append(
                ShiftOutcome(workout_id=wid, name=name, dates=dates, status="updated")
            )
        except Exception as exc:
            outcomes.append(
                ShiftOutcome(
                    workout_id=wid, name=name, dates=dates, status="failed", reason=str(exc)
                )
            )

    return ShiftResult(
        dry_run=req.dry_run,
        updated=sum(1 for o in outcomes if o.status in ("updated", "would_update")),
        skipped=sum(1 for o in outcomes if o.status == "skipped"),
        failed=sum(1 for o in outcomes if o.status == "failed"),
        outcomes=outcomes,
    )


@router.get(
    "/review/{activity_id}",
    summary="How a completed activity compared with the workout prescribed for it",
)
def review(
    activity_id: int,
    provider: FitnessProvider = Depends(get_garmin),
) -> dict[str, Any]:
    """Derived, not remembered — nothing about the session is stored anywhere.

    Matching is by date: whatever was on the calendar the day the activity
    happened. More than one workout on a day is common once a Coach plan and a
    FitStack plan overlap, so prefer one carrying a target we can actually judge
    against rather than whichever Garmin happens to list first.
    """
    activity = provider.activity_detail(activity_id)
    day_iso = (activity.get("start_local") or "")[:10]

    workout_detail: dict[str, Any] | None = None
    if day_iso:
        try:
            day = date.fromisoformat(day_iso)
            candidates = [s for s in provider.scheduled_on(day) if s.get("workout_id")]
            for cand in candidates:
                detail = provider.workout_detail(cand["workout_id"])
                steps = [
                    s for seg in (detail.get("segments") or []) for s in (seg.get("steps") or [])
                ]
                if primary_target(steps) is not None:
                    workout_detail = detail
                    break
                # Keep the first as a fallback so the response still names what
                # was scheduled, even when nothing is comparable.
                if workout_detail is None:
                    workout_detail = detail
        except Exception as exc:  # pragma: no cover - upstream flakiness
            log.warning("review: could not resolve the scheduled workout (%s)", exc)

    return review_session(activity, workout_detail)

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status

from app.deps import get_garmin
from app.providers.base import FitnessProvider
from app.schemas.health import (
    PushBody,
    RunningWorkoutSpec,
    ScheduleBody,
    WorkoutSummary,
)

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.get("", response_model=list[WorkoutSummary], summary="List workout templates on the account")
def list_workouts(
    limit: int = Query(100, ge=1, le=200),
    provider: FitnessProvider = Depends(get_garmin),
) -> list[WorkoutSummary]:
    return [WorkoutSummary(**w) for w in provider.list_workouts(limit=limit)]


@router.post("/running", status_code=status.HTTP_201_CREATED, summary="Create a running workout template")
def create_running_workout(
    spec: RunningWorkoutSpec,
    provider: FitnessProvider = Depends(get_garmin),
) -> dict:
    try:
        return provider.create_running_workout(spec.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.put("/{workout_id}", summary="Replace a running workout template in place")
def update_running_workout(
    workout_id: int,
    spec: RunningWorkoutSpec,
    provider: FitnessProvider = Depends(get_garmin),
) -> dict:
    """Whole-workout replacement. The id survives, so existing calendar entries
    for this workout pick up the change rather than being orphaned."""
    try:
        return provider.update_running_workout(workout_id, spec.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{workout_id}/schedule", summary="Schedule a workout on a specific date")
def schedule(
    workout_id: int,
    body: ScheduleBody,
    provider: FitnessProvider = Depends(get_garmin),
) -> dict:
    return provider.schedule_workout(workout_id, body.date)


@router.post("/{workout_id}/push", summary="Push a workout to a device (default: last-used)")
def push_to_device(
    workout_id: int,
    body: PushBody,
    provider: FitnessProvider = Depends(get_garmin),
) -> dict:
    return provider.push_workout_to_device(workout_id, body.device_id)


@router.delete("/{workout_id}", summary="Delete a workout template")
def delete(
    workout_id: int,
    provider: FitnessProvider = Depends(get_garmin),
) -> dict | None:
    return provider.delete_workout(workout_id)


@router.delete("/schedule/{scheduled_id}", summary="Unschedule a workout from the calendar")
def unschedule(
    scheduled_id: int,
    provider: FitnessProvider = Depends(get_garmin),
) -> dict | None:
    return provider.unschedule_workout(scheduled_id)

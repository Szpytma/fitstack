from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StrengthExercise(BaseModel):
    """One movement. Weight is optional on purpose — see `strength_plan.py`."""

    exercise_name: str = Field(..., min_length=1, max_length=80)
    sets: int = Field(..., ge=1, le=10)
    reps: int = Field(..., ge=1, le=100)
    rest_s: int = Field(90, ge=0, le=600)
    weight_kg: float | None = Field(None, ge=0, le=500)
    #: Only needed when `exercise_name` is not in the Garmin catalogue; the
    #: provider resolves the category from the name otherwise.
    category: str | None = Field(None, max_length=40)


class StrengthWarmup(BaseModel):
    """A timed machine warm-up. Held on time, not reps."""

    exercise_name: str = Field(..., min_length=1, max_length=80)
    duration_s: int = Field(600, ge=60, le=3600)
    category: str | None = Field(None, max_length=40)


class StrengthWorkoutSpec(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    estimated_duration_s: int | None = None
    warmup: StrengthWarmup | None = None
    exercises: list[StrengthExercise] = Field(..., min_length=1, max_length=20)


class StrengthSession(BaseModel):
    date: str
    day: str
    focus: Literal["lower", "upper", "upper_light"]
    focus_label: str
    title: str
    note: str | None = None
    estimated_duration_s: int | None = None
    warmup: StrengthWarmup | None = None
    exercises: list[StrengthExercise]
    spec: StrengthWorkoutSpec | None = None


class StrengthWeek(BaseModel):
    index: int
    start: str
    end: str
    sets: int
    reps: int
    deload: bool
    note: str | None = None
    sessions: list[StrengthSession]


class StrengthPlan(BaseModel):
    plan_name: str
    weeks_total: int
    days: list[str]
    long_run_day: str
    sessions_per_week: int
    notes: list[str] = []
    weeks: list[StrengthWeek]


class StrengthWeekView(BaseModel):
    """One week of the strength block, alongside where it sits in the arc."""

    plan_name: str
    week_number: int
    weeks_total: int
    days: list[str]
    notes: list[str] = []
    week: StrengthWeek


class StrengthApplySession(BaseModel):
    date: str
    spec: StrengthWorkoutSpec


class StrengthApplyRequest(BaseModel):
    sessions: list[StrengthApplySession] = Field(..., min_length=1, max_length=60)
    #: Remove strength workouts already scheduled in this date range first, so a
    #: re-push replaces rather than doubles up.
    replace_existing: bool = True


class StrengthApplyResult(BaseModel):
    created: int
    scheduled: int
    removed: int
    failures: list[str]
    workout_ids: list[int]

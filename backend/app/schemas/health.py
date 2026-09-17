from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class DailySummary(BaseModel):
    date: str
    steps: int | None = None
    step_goal: int | None = None
    calories_kcal: float | None = None
    distance_m: float | None = None
    active_minutes: int | None = None
    resting_hr: int | None = None
    min_hr: int | None = None
    max_hr: int | None = None
    last_sync_gmt: str | None = None
    wellness_start_local: str | None = None
    wellness_end_gmt: str | None = None


class SleepSummary(BaseModel):
    date: str
    sleep_seconds: int | None = None
    deep_seconds: int | None = None
    light_seconds: int | None = None
    rem_seconds: int | None = None
    awake_seconds: int | None = None
    sleep_score: int | None = None


class HeartRatePayload(BaseModel):
    date: str
    resting_hr: int | None = None
    min_hr: int | None = None
    max_hr: int | None = None
    hr_values: list[list[int | None]] | None = None


class ActivitySummary(BaseModel):
    activity_id: int | None = None
    name: str | None = None
    type: str | None = None
    start_local: str | None = None
    duration_s: float | None = None
    distance_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    calories_kcal: float | None = None
    avg_speed_mps: float | None = None
    elevation_gain_m: float | None = None


class UpcomingWorkout(BaseModel):
    date: str
    scheduled_id: int | None = None
    workout_id: int
    title: str | None = None
    sport: str | None = None
    atp_plan_id: int | None = None


class WorkoutSummary(BaseModel):
    workout_id: int
    name: str | None = None
    sport: str | None = None
    estimated_duration_s: int | None = None
    updated: str | None = None


class Device(BaseModel):
    device_id: int | None = None
    name: str | None = None
    product: str | None = None
    last_sync_local: str | None = None


class ActivitySeries(BaseModel):
    time_s: list[int | None]
    distance_m: list[float | None]
    hr: list[float | None]
    pace_min_per_km: list[float | None]
    altitude_m: list[float | None]
    lat: list[float | None]
    lon: list[float | None]


class ActivityLap(BaseModel):
    lap: int | None = None
    distance_m: float | None = None
    duration_s: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_speed_mps: float | None = None
    elevation_gain_m: float | None = None


class ActivityHrZone(BaseModel):
    zone: int | None = None
    seconds: float | None = None
    low_bpm: float | None = None


class ActivityWeather(BaseModel):
    temp_c: float | None = None
    apparent_c: float | None = None
    humidity: float | None = None
    wind_kph: float | None = None
    conditions: str | None = None


class ActivityDetail(BaseModel):
    activity_id: int
    name: str | None = None
    type: str | None = None
    start_local: str | None = None
    duration_s: float | None = None
    distance_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_speed_mps: float | None = None
    avg_pace_min_per_km: float | None = None
    calories_kcal: float | None = None
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    series: ActivitySeries
    polyline: list[list[float]]
    splits: list[ActivityLap]
    hr_zones: list[ActivityHrZone]
    weather: ActivityWeather


# ---------- write ----------
class PaceTarget(BaseModel):
    type: Literal["pace"] = "pace"
    low_mps: float = Field(..., description="Slower end of pace zone in meters/second")
    high_mps: float = Field(..., description="Faster end of pace zone in meters/second")


class HrTarget(BaseModel):
    type: Literal["hr"] = "hr"
    low_bpm: int
    high_bpm: int


Target = PaceTarget | HrTarget


class WorkoutStep(BaseModel):
    kind: Literal["warmup", "interval", "recovery", "cooldown", "repeat"]
    duration_s: float | None = None
    iterations: int | None = None
    target: Target | None = None
    steps: list["WorkoutStep"] | None = None


class RunningWorkoutSpec(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    estimated_duration_s: int | None = None
    steps: list[WorkoutStep] = Field(..., min_length=1)


class ScheduleBody(BaseModel):
    date: date


class PushBody(BaseModel):
    device_id: int | None = None


WorkoutStep.model_rebuild()

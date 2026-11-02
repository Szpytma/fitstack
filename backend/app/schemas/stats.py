from __future__ import annotations

from pydantic import BaseModel


class AthleteProfile(BaseModel):
    height_cm: float | None = None
    weight_kg: float | None = None
    birth_date: str | None = None
    gender: str | None = None


class LoadBucket(BaseModel):
    """One of Garmin's three load buckets, with the range it wants it inside."""

    bucket: str
    load: float | None = None
    target_min: float | None = None
    target_max: float | None = None


class TrainingStatus(BaseModel):
    date: str
    vo2max: float | None = None
    vo2max_measured: str | None = None
    status: int | None = None
    feedback: str | None = None
    acute_load: float | None = None
    chronic_load: float | None = None
    acwr: float | None = None
    acwr_status: str | None = None
    balance_feedback: str | None = None
    load_balance: list[LoadBucket] = []


class Hrv(BaseModel):
    date: str
    weekly_avg: int | None = None
    last_night: int | None = None
    status: str | None = None
    feedback: str | None = None
    baseline_low_upper: int | None = None
    baseline_balanced_low: int | None = None
    baseline_balanced_high: int | None = None


class ReadinessFactor(BaseModel):
    factor: str
    percent: int | None = None
    feedback: str | None = None


class TrainingReadiness(BaseModel):
    date: str
    score: int | None = None
    level: str | None = None
    feedback: str | None = None
    measured_at: str | None = None
    context: str | None = None
    sleep_score: int | None = None
    recovery_time_min: int | None = None
    acute_load: float | None = None
    #: The day's last reading — low right after a session, which is the point.
    latest_score: int | None = None
    latest_recovery_time_min: int | None = None
    factors: list[ReadinessFactor] = []


class FitnessAgeComponent(BaseModel):
    name: str
    value: float | None = None
    target_value: float | None = None
    improvement_value: float | None = None
    potential_age: float | None = None
    #: 1 is the component holding the fitness age back hardest.
    priority: int | None = None


class FitnessAge(BaseModel):
    date: str
    chronological: float | None = None
    fitness: float | None = None
    achievable: float | None = None
    updated: str | None = None
    components: list[FitnessAgeComponent] = []


class RacePredictions(BaseModel):
    date: str | None = None
    time_5k_s: int | None = None
    time_10k_s: int | None = None
    time_half_s: int | None = None
    time_marathon_s: int | None = None


class StatsOverview(BaseModel):
    """Every metric Garmin computes for one day, in one response.

    Each block is optional on purpose: these come from separate upstream
    endpoints and one of them being down is not a reason to show the athlete
    nothing. `warnings` names whatever did not arrive.
    """

    date: str
    profile: AthleteProfile | None = None
    training_status: TrainingStatus | None = None
    hrv: Hrv | None = None
    readiness: TrainingReadiness | None = None
    fitness_age: FitnessAge | None = None
    race_predictions: RacePredictions | None = None
    warnings: list[str] = []


class WeightPoint(BaseModel):
    day: str
    weight_kg: float
    bmi: float | None = None


class WeightHistory(BaseModel):
    height_cm: float | None = None
    #: Mass at BMI 30 for this athlete's height — the obesity threshold, and the
    #: only reference line on the chart that means anything clinically.
    bmi30_kg: float | None = None
    points: list[WeightPoint] = []


class StatsWeek(BaseModel):
    """One training week: what was planned, what was run, what it cost.

    `ef_median` is the block's progress measure — see `adapt.py`. It is null
    when no run that week fell inside the aerobic window, which is a real
    answer, not a gap.
    """

    week_start: str
    week_end: str
    week_no: int | None = None
    planned_minutes: int | None = None
    actual_minutes: int = 0
    km: float = 0.0
    runs: int = 0
    ef_median: float | None = None
    ef_runs: int = 0

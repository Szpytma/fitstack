from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.health import RunningWorkoutSpec


def parse_goal_time(value: str) -> float:
    """'1:45:00' | '45:00' | '2700' → seconds."""
    v = value.strip()
    if not v:
        raise ValueError("empty goal time")
    if ":" not in v:
        return float(v)
    parts = [float(p) for p in v.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError("goal time must look like 1:45:00 or 45:00")


class PlanRequest(BaseModel):
    # Base mode has no race: distance and date are ignored, `weeks` and
    # `weekly_minutes` drive it instead.
    mode: Literal["race", "base"] = "race"
    weeks: int = Field(12, ge=4, le=24)
    weekly_minutes: float | None = Field(None, ge=0, le=1200)
    race_km: float = Field(0, ge=0, le=200)
    race_date: date | None = None
    runs_per_week: int = Field(4, ge=2, le=7)
    long_run_day: str = "Sunday"
    weekly_km: float | None = Field(None, ge=0, le=300)
    goal_time: str | None = None
    race_name: str | None = Field(None, max_length=80)
    # False when planning for someone else — the account holder's runs must not
    # become the basis for another athlete's paces.
    use_history: bool = True
    # "hr" retargets every session by heart rate instead of pace. Needs HR in the
    # history to estimate max from; falls back to pace with a warning if absent.
    target_mode: Literal["pace", "hr"] = "pace"

    @field_validator("goal_time")
    @classmethod
    def _check_goal(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        parse_goal_time(v)  # raises if malformed
        return v

    @property
    def goal_time_s(self) -> float | None:
        return parse_goal_time(self.goal_time) if self.goal_time else None


class PlanSession(BaseModel):
    date: str
    day: str
    kind: Literal["long", "quality", "easy", "recovery", "race"]
    title: str
    distance_km: float
    duration_s: int
    pace_label: str
    # Set only in HR mode — what the watch will chase for this session.
    hr_label: str | None = None
    note: str | None = None
    spec: RunningWorkoutSpec | None = None


class PlanWeek(BaseModel):
    index: int
    start: str
    end: str
    phase: Literal["base", "build", "peak", "taper", "race"]
    volume_km: float
    planned_km: float
    # Base mode prescribes time, not distance — km is only an estimate there.
    planned_minutes: int | None = None
    down_week: bool
    sessions: list[PlanSession]


class PlanBasis(BaseModel):
    source: Literal["goal_time", "recent_activities", "stated_volume"]
    threshold_mps: float
    threshold_pace: str
    projected_race_time: str | None = None
    reference: str | None = None
    reference_activity_id: int | None = None
    weekly_km_observed: float | None = None
    paces: dict[str, str]


class PlanHrBasis(BaseModel):
    max_hr: int
    # Where max HR came from: the athlete's Garmin zone setup (with or without a
    # full zone ladder), or inferred from recent runs as a last resort.
    source: Literal["garmin_zones", "garmin_max_hr", "recent_activities"]
    reference: str | None = None
    resting_hr: int | None = None
    zones: dict[str, str]


class RacePlan(BaseModel):
    race_name: str | None = None
    race_km: float
    race_date: str
    weeks_total: int
    runs_per_week: int
    long_run_day: str
    peak_week_km: float
    total_km: float
    basis: PlanBasis
    # "pace" whenever HR retargeting was not asked for, or could not be done.
    target_mode: Literal["pace", "hr"] = "pace"
    hr_basis: PlanHrBasis | None = None
    warnings: list[str]
    weeks: list[PlanWeek]


class PlanCompliance(BaseModel):
    """What the previous week actually delivered, against what it asked for.

    Reported, never acted on — the volume ramp stays anchored either way.
    """

    week_number: int
    start: str
    end: str
    planned_km: float
    actual_km: float
    ratio: float | None = None
    runs_done: int
    runs_planned: int


class PlanDecision(BaseModel):
    """Why the upcoming week advances, holds, or steps back."""

    week_number: int
    action: Literal["advance", "hold", "step_back"]
    scale: float
    reasons: list[str]
    looked_at: list[dict] = []
    ef_baseline: float | None = None


class PlanWeekView(BaseModel):
    """One week of a rolling plan, with enough context to act on it alone."""

    race_name: str | None = None
    race_km: float
    race_date: str
    week_number: int
    weeks_total: int
    weeks_remaining_after_this: int
    target_mode: Literal["pace", "hr"] = "pace"
    basis: PlanBasis
    hr_basis: PlanHrBasis | None = None
    warnings: list[str]
    # How the previous week actually went. Null while it is still running.
    last_week: PlanCompliance | None = None
    # The adaptation decision behind this week, and what it would have been.
    decision: PlanDecision | None = None
    original_planned_km: float | None = None
    # True when this week comes before the race block opens — aerobic base, not
    # race work. See `active_plan.lead_in_view`.
    lead_in: bool = False
    race_block_opens: str | None = None
    week: PlanWeek


class PlanStatus(BaseModel):
    """Where the athlete is in the block, without rebuilding the plan."""

    race_name: str | None = None
    race_km: float
    race_date: str
    started: str
    days_to_race: int
    weeks_to_race: int
    runs_per_week: int
    long_run_day: str
    target_mode: Literal["pace", "hr"]
    anchor_weekly_km: float
    next_week_starts: str
    block_weeks: int | None = None
    race_block_opens: str | None = None
    lead_in_weeks: int = 0


class PlanApplySession(BaseModel):
    date: date
    spec: RunningWorkoutSpec


class PlanApplyRequest(BaseModel):
    """Sessions to push to Garmin — normally taken straight from a preview."""

    sessions: list[PlanApplySession] = Field(..., min_length=1, max_length=200)


class PlanApplyResult(BaseModel):
    templates_created: int
    scheduled: int
    failures: list[str]
    workout_ids: list[int]

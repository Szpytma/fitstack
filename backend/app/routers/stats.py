from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date as date_cls, timedelta
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query

from app import active_plan, adapt
from app.deps import get_garmin
from app.providers.base import FitnessProvider
from app.schemas.stats import (
    AthleteProfile,
    FitnessAge,
    Hrv,
    RacePredictions,
    StatsOverview,
    StatsWeek,
    TrainingReadiness,
    TrainingStatus,
    WeightHistory,
    WeightPoint,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])

T = TypeVar("T")

#: BMI 30 — where overweight becomes obese, and the only body-mass line on the
#: chart with a clinical meaning behind it. Garmin's own fitness-age model
#: targets BMI 21, which is not a useful goal for most people and is shown as a
#: component figure rather than drawn as a line.
BMI_OBESE = 30.0


def _try(label: str, warnings: list[str], fetch: Callable[[], T]) -> T | None:
    """Run one upstream read, recording a failure instead of raising.

    The overview stitches together six independent Garmin endpoints. Any of
    them can be missing for an account (no HRV-capable watch, no fitness age
    before enough data accumulates) or simply down. Showing the athlete nothing
    because one block failed is worse than showing five and naming the sixth.
    """
    try:
        return fetch()
    except NotImplementedError:
        warnings.append(f"{label}: not supported by this provider")
    except Exception as exc:  # pragma: no cover - upstream flakiness
        log.warning("stats/overview: %s failed (%s)", label, exc)
        warnings.append(f"{label}: {exc}")
    return None


@router.get(
    "/overview",
    response_model=StatsOverview,
    summary="Every metric Garmin computes for one day",
)
def overview(
    day: date_cls | None = Query(None, description="Defaults to today."),
    provider: FitnessProvider = Depends(get_garmin),
) -> StatsOverview:
    when = day or date_cls.today()
    warnings: list[str] = []

    profile = _try("profile", warnings, provider.athlete_profile)
    status = _try("training_status", warnings, lambda: provider.training_status(when))
    hrv = _try("hrv", warnings, lambda: provider.hrv(when))
    readiness = _try("readiness", warnings, lambda: provider.training_readiness(when))
    age = _try("fitness_age", warnings, lambda: provider.fitness_age(when))
    races = _try("race_predictions", warnings, provider.race_predictions)

    if not any((profile, status, hrv, readiness, age, races)):
        raise HTTPException(
            status_code=502,
            detail="Could not read any training metric from the provider: "
            + "; ".join(warnings),
        )

    return StatsOverview(
        date=when.isoformat(),
        profile=AthleteProfile(**profile) if profile else None,
        training_status=TrainingStatus(**status) if status else None,
        hrv=Hrv(**hrv) if hrv else None,
        readiness=TrainingReadiness(**readiness) if readiness else None,
        fitness_age=FitnessAge(**age) if age else None,
        race_predictions=RacePredictions(**races) if races else None,
        warnings=warnings,
    )


@router.get("/weight", response_model=WeightHistory, summary="Weigh-ins, with BMI")
def weight(
    days: int = Query(180, ge=7, le=730),
    provider: FitnessProvider = Depends(get_garmin),
) -> WeightHistory:
    """Manual weigh-ins over the window, with BMI derived from stored height.

    Height is read from the account rather than inferred from a reported BMI —
    that BMI was computed *from* the height, so deriving it back is circular and
    silently wrong the moment Garmin changes how it rounds.
    """
    end = date_cls.today()
    start = end - timedelta(days=days)
    points = provider.weight_history(start, end)

    height_cm: float | None = None
    try:
        height_cm = (provider.athlete_profile() or {}).get("height_cm")
    except Exception as exc:  # pragma: no cover - upstream flakiness
        log.warning("stats/weight: no height on the profile (%s)", exc)

    m = float(height_cm) / 100.0 if height_cm else None
    return WeightHistory(
        height_cm=height_cm,
        bmi30_kg=round(BMI_OBESE * m * m, 1) if m else None,
        points=[
            WeightPoint(
                day=p["day"],
                weight_kg=p["weight_kg"],
                bmi=round(p["weight_kg"] / (m * m), 1) if m else None,
            )
            for p in points
        ],
    )


@router.get(
    "/weeks",
    response_model=list[StatsWeek],
    summary="Training week by week, with efficiency factor",
)
def weeks(
    weeks_back: int = Query(24, ge=1, le=104, alias="weeks"),
    limit: int = Query(250, ge=20, le=500, description="Activities to read."),
    provider: FitnessProvider = Depends(get_garmin),
) -> list[StatsWeek]:
    """Calendar weeks of running, with planned minutes where a plan covers them.

    Planned volume comes from replaying the active block off its pinned anchor,
    *with the adaptation scales applied*, because that is what the athlete was
    actually given — `/plan/week` serves the adapted figure, and a stats page
    quoting the unadjusted one would disagree with the calendar and the watch.
    Weeks before the block started simply have none.
    """
    zones = provider.heart_rate_zones() or {}
    activities = provider.activities(limit=limit)
    today = date_cls.today()
    since = today - timedelta(weeks=weeks_back)

    series = adapt.week_series(activities, zones.get("max_hr"), since=since)

    planned: dict[str, tuple[int, int | None]] = {}
    plan = active_plan.load()
    if plan is not None:
        try:
            # Unadjusted first — it is the yardstick the decisions are measured
            # against. Re-levelling against an already-scaled block ratchets the
            # plan downwards; see `adapt.adapted_view` for the same two passes.
            original = active_plan.rebuild(plan, activities, zones or None)
            weeks_out = original.get("weeks") or []
            scales, _ = adapt.scales_through(
                original,
                max((int(w["index"]) for w in weeks_out), default=1),
                activities,
                zones.get("max_hr"),
                today,
                plan.start_date,
            )
            adjusted = (
                active_plan.rebuild(plan, activities, zones or None, scales)
                if scales
                else original
            )
            planned = {
                str(w["start"]): (int(w["index"]), w.get("planned_minutes"))
                for w in adjusted.get("weeks") or []
            }
        except Exception as exc:  # pragma: no cover - planner guards its own inputs
            log.warning("stats/weeks: could not replay the active plan (%s)", exc)

    out: list[StatsWeek] = []
    for w in series:
        no, mins = planned.get(w["week_start"], (None, None))
        out.append(
            StatsWeek(
                week_no=no,
                planned_minutes=int(mins) if mins else None,
                **w,
            )
        )
    return out

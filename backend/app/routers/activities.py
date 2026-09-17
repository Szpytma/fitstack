from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.deps import get_garmin
from app.providers.base import FitnessProvider
from app.schemas.health import ActivityDetail, ActivitySummary

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=list[ActivitySummary], summary="Most recent activities")
def list_activities(
    limit: int = Query(20, ge=1, le=100),
    provider: FitnessProvider = Depends(get_garmin),
) -> list[ActivitySummary]:
    return [ActivitySummary(**a) for a in provider.activities(limit=limit)]


@router.get(
    "/{activity_id}",
    response_model=ActivityDetail,
    summary="Full activity detail: HR/pace/altitude series, GPS polyline, splits, HR zones, weather",
)
def activity_detail(
    activity_id: int,
    provider: FitnessProvider = Depends(get_garmin),
) -> ActivityDetail:
    return ActivityDetail(**provider.activity_detail(activity_id))

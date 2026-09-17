from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date as date_cls, timedelta
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_garmin
from app.providers.base import FitnessProvider
from app.schemas.health import DailySummary, HeartRatePayload, SleepSummary

log = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

T = TypeVar("T")


def _collect_days(days: int, label: str, fetch: Callable[[date_cls], T]) -> list[T]:
    """Walk back `days` from today, skipping days the provider can't serve.

    A gap is normal — the watch wasn't worn, or Garmin has nothing for that
    date — so a short list is a valid answer. What is not valid is staying
    silent about it: every skipped day is logged, and a run where *nothing*
    succeeded is an upstream failure, not an empty history.
    """
    end = date_cls.today()
    out: list[T] = []
    failed: list[str] = []

    for i in range(days):
        d = end - timedelta(days=i)
        try:
            out.append(fetch(d))
        except Exception as exc:  # pragma: no cover - upstream flakiness
            failed.append(d.isoformat())
            log.warning("%s: no data for %s (%s)", label, d, exc)

    if failed:
        log.warning(
            "%s: returning %d of %d requested day(s); missing %s",
            label,
            len(out),
            days,
            ", ".join(failed),
        )

    if not out and days:
        raise HTTPException(
            status_code=502,
            detail=f"Could not read {label} for any of the last {days} day(s) from the provider.",
        )

    return out


@router.get("/today", response_model=DailySummary)
def today(provider: FitnessProvider = Depends(get_garmin)) -> DailySummary:
    return DailySummary(**provider.daily_summary(date_cls.today()))


@router.get("/summary/{day}", response_model=DailySummary)
def summary(day: date_cls, provider: FitnessProvider = Depends(get_garmin)) -> DailySummary:
    return DailySummary(**provider.daily_summary(day))


@router.get("/heart-rate/{day}", response_model=HeartRatePayload)
def heart_rate(day: date_cls, provider: FitnessProvider = Depends(get_garmin)) -> HeartRatePayload:
    return HeartRatePayload(**provider.heart_rate(day))


@router.get("/sleep/{day}", response_model=SleepSummary)
def sleep(day: date_cls, provider: FitnessProvider = Depends(get_garmin)) -> SleepSummary:
    return SleepSummary(**provider.sleep(day))


@router.get("/sleep-history", response_model=list[SleepSummary], summary="Last N days of sleep")
def sleep_history(
    days: int = Query(14, ge=1, le=60),
    provider: FitnessProvider = Depends(get_garmin),
) -> list[SleepSummary]:
    return _collect_days(days, "sleep-history", lambda d: SleepSummary(**provider.sleep(d)))


@router.get("/summary-history", response_model=list[DailySummary], summary="Last N days of daily summaries")
def summary_history(
    days: int = Query(14, ge=1, le=60),
    provider: FitnessProvider = Depends(get_garmin),
) -> list[DailySummary]:
    return _collect_days(
        days, "summary-history", lambda d: DailySummary(**provider.daily_summary(d))
    )

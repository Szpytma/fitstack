from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_garmin
from app.providers.base import FitnessProvider
from app.schemas.health import Device

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[Device], summary="Connected devices")
def list_devices(provider: FitnessProvider = Depends(get_garmin)) -> list[Device]:
    return [Device(**d) for d in provider.list_devices()]

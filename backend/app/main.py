from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import activities, auth, coach, devices, health, plan, workouts
from app.routers.auth import AuthDep

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="FitStack",
    version="0.3.0",
    description=(
        "Local aggregation of fitness data. Stage 1-3: Garmin read + write. "
        "Strava provider slot is reserved but disabled until credentials are configured."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["meta"])
def root() -> dict[str, str | list[str]]:
    providers_enabled = ["garmin"]
    if settings.strava_configured:
        providers_enabled.append("strava (configured but not implemented yet)")
    return {
        "app": "fitstack",
        "version": "0.3.0",
        "docs": "/docs",
        "providers_enabled": providers_enabled,
    }


@app.get("/healthz", tags=["meta"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# /auth is deliberately open — it is how you get a session in the first place.
app.include_router(auth.router)

# Everything touching Garmin data or the account requires a session. Applied at
# include time so a new router cannot forget it.
for _router in (
    health.router,
    activities.router,
    coach.router,
    workouts.router,
    devices.router,
    plan.router,
):
    app.include_router(_router, dependencies=[AuthDep])

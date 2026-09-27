from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class FitnessProvider(ABC):
    """Abstract base for a fitness data source (Garmin, Strava, ...).

    Each concrete provider translates its own API into these normalized
    methods. Endpoints only ever see this interface, so adding a new
    provider does not require touching routers.
    """

    name: str

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider has credentials/tokens and can serve calls."""

    # ---------- read ----------
    @abstractmethod
    def daily_summary(self, day: date) -> dict[str, Any]: ...

    @abstractmethod
    def heart_rate(self, day: date) -> dict[str, Any]: ...

    @abstractmethod
    def activities(self, limit: int = 20) -> list[dict[str, Any]]: ...

    @abstractmethod
    def sleep(self, day: date) -> dict[str, Any]: ...

    @abstractmethod
    def upcoming_workouts(self, days_ahead: int = 14) -> list[dict[str, Any]]: ...

    @abstractmethod
    def workout_detail(self, workout_id: int | str) -> dict[str, Any]: ...

    @abstractmethod
    def activity_laps(self, activity_id: int | str) -> list[dict[str, Any]]:
        """Lap splits for one activity, cheaply — see `laps.py` for why.

        Optional: a provider without lap data raises, and the callers fall back
        to reading the activity as a steady run.
        """
        raise NotImplementedError

    def activity_detail(self, activity_id: int | str) -> dict[str, Any]:
        """Return per-activity time series (HR/pace/altitude), GPS polyline, splits, weather, HR zones."""

    @abstractmethod
    def list_workouts(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return workout templates on the account."""

    @abstractmethod
    def list_devices(self) -> list[dict[str, Any]]:
        """Return connected devices (for the push-to-device dropdown)."""

    @abstractmethod
    def scheduled_on(self, day: date) -> list[dict[str, Any]]:
        """Workouts on the calendar for one date, past or future."""

    @abstractmethod
    def heart_rate_zones(self) -> dict[str, Any] | None:
        """The athlete's configured max HR and zone floors, or None if unset.

        {max_hr, resting_hr, lactate_threshold_hr, training_method, zone_floors}
        — `zone_floors` is five ascending bpm values, or None if incomplete.
        Providers without a zone concept return None rather than raising.
        """

    # ---------- write (Garmin only; Strava will raise NotImplementedError) ----------
    @abstractmethod
    def create_running_workout(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Upload a running workout from a normalized spec. See routers/workouts.py."""

    @abstractmethod
    def update_running_workout(
        self, workout_id: int | str, spec: dict[str, Any]
    ) -> dict[str, Any]:
        """Replace a template's contents in place, keeping its id.

        Whole-workout replacement, not a patch. The id survives, so anything
        already scheduled against this workout picks up the change.
        """

    @abstractmethod
    def schedule_workout(self, workout_id: int | str, day: date) -> dict[str, Any]: ...

    @abstractmethod
    def delete_workout(self, workout_id: int | str) -> dict[str, Any] | None: ...

    @abstractmethod
    def unschedule_workout(self, scheduled_id: int | str) -> dict[str, Any] | None: ...

    @abstractmethod
    def push_workout_to_device(
        self, workout_id: int | str, device_id: int | str | None = None
    ) -> dict[str, Any]: ...

    def create_strength_workout(self, spec: dict[str, Any]) -> dict[str, Any]:
        """spec = {name, exercises: [{exercise_name, sets, reps, rest_s, weight_kg?}]}."""
        raise NotImplementedError

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)

from app.providers.base import FitnessProvider

logger = logging.getLogger(__name__)


class GarminProvider(FitnessProvider):
    """Wraps python-garminconnect. Uses cached tokens; does not accept passwords."""

    name = "garmin"

    def __init__(self, tokenstore: str) -> None:
        self.tokenstore = tokenstore
        self._client: Garmin | None = None

    # ---------- lifecycle ----------
    def _login(self) -> Garmin:
        if self._client is not None:
            return self._client
        client = Garmin()
        client.login(self.tokenstore)
        self._client = client
        logger.info("garmin: logged in from tokenstore=%s", self.tokenstore)
        return client

    def is_available(self) -> bool:
        return (Path(self.tokenstore).expanduser() / "garmin_tokens.json").exists()

    # ---------- READ: daily / summary / hr / sleep ----------
    def daily_summary(self, day: date) -> dict[str, Any]:
        raw = self._login().get_user_summary(day.isoformat()) or {}
        return {
            "date": day.isoformat(),
            "steps": raw.get("totalSteps"),
            "step_goal": raw.get("dailyStepGoal"),
            "calories_kcal": raw.get("totalKilocalories"),
            "distance_m": raw.get("totalDistanceMeters"),
            "active_minutes": raw.get("activeSeconds", 0) // 60 if raw.get("activeSeconds") else None,
            "resting_hr": raw.get("restingHeartRate"),
            "min_hr": raw.get("minHeartRate"),
            "max_hr": raw.get("maxHeartRate"),
            "last_sync_gmt": raw.get("lastSyncTimestampGMT"),
            "wellness_start_local": raw.get("wellnessStartTimeLocal"),
            "wellness_end_gmt": raw.get("wellnessEndTimeGmt"),
        }

    def heart_rate(self, day: date) -> dict[str, Any]:
        raw = self._login().get_heart_rates(day.isoformat()) or {}
        return {
            "date": day.isoformat(),
            "resting_hr": raw.get("restingHeartRate"),
            "min_hr": raw.get("minHeartRate"),
            "max_hr": raw.get("maxHeartRate"),
            "hr_values": raw.get("heartRateValues"),
        }

    def activities(self, limit: int = 20) -> list[dict[str, Any]]:
        raw = self._login().get_activities(0, limit) or []
        return [
            {
                "activity_id": a.get("activityId"),
                "name": a.get("activityName"),
                "type": (a.get("activityType") or {}).get("typeKey"),
                "start_local": a.get("startTimeLocal"),
                "duration_s": a.get("duration"),
                "distance_m": a.get("distance"),
                "avg_hr": a.get("averageHR"),
                "max_hr": a.get("maxHR"),
                "calories_kcal": a.get("calories"),
                "avg_speed_mps": a.get("averageSpeed"),
                "elevation_gain_m": a.get("elevationGain"),
            }
            for a in raw
        ]

    def sleep(self, day: date) -> dict[str, Any]:
        raw = self._login().get_sleep_data(day.isoformat()) or {}
        daily = raw.get("dailySleepDTO") or {}
        return {
            "date": day.isoformat(),
            "sleep_seconds": daily.get("sleepTimeSeconds"),
            "deep_seconds": daily.get("deepSleepSeconds"),
            "light_seconds": daily.get("lightSleepSeconds"),
            "rem_seconds": daily.get("remSleepSeconds"),
            "awake_seconds": daily.get("awakeSleepSeconds"),
            "sleep_score": (daily.get("sleepScores") or {}).get("overall", {}).get("value"),
        }

    def upcoming_workouts(self, days_ahead: int = 14) -> list[dict[str, Any]]:
        today = date.today()
        end = today + timedelta(days=days_ahead)
        client = self._login()
        months = {(today.year, today.month), (end.year, end.month)}
        items: list[dict[str, Any]] = []
        for y, m in months:
            sched = client.get_scheduled_workouts(y, m) or {}
            items.extend(sched.get("calendarItems") or [])

        # Deduplicate by the *scheduled instance*, never by workoutId: one template
        # legitimately recurs across many dates in a plan, and keying on the
        # template silently drops every date after the first. Two months are
        # fetched, so instance ids can genuinely repeat across the two responses.
        seen: set[Any] = set()
        out: list[dict[str, Any]] = []
        for it in items:
            wid = it.get("workoutId")
            sid = it.get("id")
            if (
                it.get("itemType") == "workout"
                and wid and sid is not None and sid not in seen
                and it.get("date")
                and today.isoformat() <= it["date"] <= end.isoformat()
            ):
                seen.add(sid)
                out.append({
                    "date": it.get("date"),
                    "scheduled_id": it.get("id"),
                    "workout_id": wid,
                    "title": it.get("title"),
                    "sport": it.get("sportTypeKey"),
                    "atp_plan_id": it.get("atpPlanId"),
                })
        out.sort(key=lambda it: it["date"])
        return out

    def workout_detail(self, workout_id: int | str) -> dict[str, Any]:
        raw = self._login().get_workout_by_id(int(workout_id)) or {}
        segments = []
        for seg in raw.get("workoutSegments") or []:
            steps_out = [self._normalize_step(s) for s in seg.get("workoutSteps") or []]
            segments.append({
                "segment_order": seg.get("segmentOrder"),
                "sport": (seg.get("sportType") or {}).get("sportTypeKey"),
                "steps": steps_out,
            })
        return {
            "workout_id": raw.get("workoutId"),
            "name": raw.get("workoutName"),
            "sport": (raw.get("sportType") or {}).get("sportTypeKey"),
            "estimated_duration_s": raw.get("estimatedDurationInSecs"),
            "estimated_distance_m": raw.get("estimatedDistanceInMeters"),
            "segments": segments,
        }

    def activity_laps(self, activity_id: int | str) -> list[dict[str, Any]]:
        """Just the laps — `activity_detail` also pulls the time series and map.

        Plan building reads laps for several activities at once, so it wants the
        cheap call, not the one that carries a polyline.
        """
        raw = self._login().get_activity_splits(str(int(activity_id))) or {}
        return [
            {
                "lap": s.get("lapIndex"),
                "distance_m": s.get("distance"),
                "duration_s": s.get("duration"),
                "avg_hr": s.get("averageHR"),
                "avg_speed_mps": s.get("averageSpeed"),
            }
            for s in raw.get("lapDTOs") or raw.get("laps") or []
        ]

    # ---------- READ: activity detail (map + charts) ----------
    def activity_detail(self, activity_id: int | str) -> dict[str, Any]:
        client = self._login()
        aid = str(int(activity_id))

        details = client.get_activity_details(aid, maxchart=1500, maxpoly=2000) or {}
        summary = client.get_activity(aid) or {}
        splits = client.get_activity_splits(aid) or {}
        try:
            hr_zones = client.get_activity_hr_in_timezones(aid) or []
        except Exception:
            hr_zones = []
        try:
            weather = client.get_activity_weather(aid) or {}
        except Exception:
            weather = {}

        summary_dto = summary.get("summaryDTO") or {}
        metric_desc = details.get("metricDescriptors", []) or []
        metric_map = {m["key"]: m["metricsIndex"] for m in metric_desc if "key" in m and "metricsIndex" in m}

        idx_hr = metric_map.get("directHeartRate")
        idx_speed = metric_map.get("directSpeed")
        idx_alt = metric_map.get("directElevation")
        idx_lat = metric_map.get("directLatitude")
        idx_lon = metric_map.get("directLongitude")
        idx_time = metric_map.get("directTimestamp") or metric_map.get("sumElapsedDuration")
        idx_dist = metric_map.get("sumDistance")

        raw_metrics = details.get("activityDetailMetrics", []) or []
        series = {
            "time_s": [],       # elapsed seconds from start
            "distance_m": [],
            "hr": [],
            "pace_min_per_km": [],  # derived from speed
            "altitude_m": [],
            "lat": [],
            "lon": [],
        }

        first_ts: float | None = None
        for row in raw_metrics:
            m = row.get("metrics") or []
            def g(i: int | None) -> Any:
                return m[i] if i is not None and i < len(m) else None

            ts = g(idx_time)
            if ts is None:
                continue
            if first_ts is None:
                first_ts = float(ts)
            elapsed = (float(ts) - first_ts) / 1000.0 if idx_time and "Timestamp" in (metric_desc[idx_time].get("key", "")) else float(ts)

            speed = g(idx_speed)
            pace = None
            if speed and speed > 0:
                pace = (1000.0 / speed) / 60.0  # min/km

            series["time_s"].append(round(elapsed))
            series["distance_m"].append(g(idx_dist))
            series["hr"].append(g(idx_hr))
            series["pace_min_per_km"].append(round(pace, 2) if pace is not None else None)
            series["altitude_m"].append(g(idx_alt))
            series["lat"].append(g(idx_lat))
            series["lon"].append(g(idx_lon))

        polyline: list[list[float]] = []
        for lat, lon in zip(series["lat"], series["lon"]):
            if lat is not None and lon is not None:
                polyline.append([lat, lon])

        splits_out = []
        for s in splits.get("lapDTOs") or splits.get("laps") or []:
            splits_out.append({
                "lap": s.get("lapIndex"),
                "distance_m": s.get("distance"),
                "duration_s": s.get("duration"),
                "avg_hr": s.get("averageHR"),
                "max_hr": s.get("maxHR"),
                "avg_speed_mps": s.get("averageSpeed"),
                "elevation_gain_m": s.get("elevationGain"),
            })

        hr_zones_out = []
        for z in hr_zones:
            hr_zones_out.append({
                "zone": z.get("zoneNumber"),
                "seconds": z.get("secsInZone"),
                "low_bpm": z.get("zoneLowBoundary"),
            })

        weather_out: dict[str, Any] = {}
        if weather:
            def to_c(v: float | None) -> float | None:
                # Garmin returns temp in the user's account unit (F or C).
                # Heuristic: values > 45 must be Fahrenheit for real-world weather.
                if v is None:
                    return None
                return (v - 32) * 5 / 9 if v > 45 else v

            weather_out = {
                "temp_c": to_c(weather.get("temp")),
                "apparent_c": to_c(weather.get("apparentTemp")),
                "humidity": weather.get("relativeHumidity"),
                "wind_kph": weather.get("windSpeed"),
                "conditions": (weather.get("weatherTypeDTO") or {}).get("desc"),
            }

        return {
            "activity_id": int(aid),
            "name": summary.get("activityName"),
            "type": (summary.get("activityTypeDTO") or {}).get("typeKey"),
            "start_local": summary_dto.get("startTimeLocal"),
            "duration_s": summary_dto.get("duration"),
            "distance_m": summary_dto.get("distance"),
            "avg_hr": summary_dto.get("averageHR"),
            "max_hr": summary_dto.get("maxHR"),
            "avg_speed_mps": summary_dto.get("averageSpeed"),
            "avg_pace_min_per_km": (
                round((1000.0 / summary_dto["averageSpeed"]) / 60.0, 2)
                if summary_dto.get("averageSpeed") else None
            ),
            "calories_kcal": summary_dto.get("calories"),
            "elevation_gain_m": summary_dto.get("elevationGain"),
            "elevation_loss_m": summary_dto.get("elevationLoss"),
            "series": series,
            "polyline": polyline,
            "splits": splits_out,
            "hr_zones": hr_zones_out,
            "weather": weather_out,
        }

    def list_workouts(self, limit: int = 100) -> list[dict[str, Any]]:
        raw = self._login().get_workouts(start=0, limit=limit) or []
        return [
            {
                "workout_id": w.get("workoutId"),
                "name": w.get("workoutName"),
                "sport": (w.get("sportType") or {}).get("sportTypeKey"),
                "estimated_duration_s": w.get("estimatedDurationInSecs"),
                "updated": w.get("updatedDate"),
            }
            for w in raw
        ]

    def list_devices(self) -> list[dict[str, Any]]:
        raw = self._login().get_devices() or []
        return [
            {
                "device_id": d.get("deviceId") or d.get("userDeviceId"),
                "name": d.get("productDisplayName") or d.get("displayName"),
                "product": d.get("productNumber"),
                "last_sync_local": d.get("lastSyncTime"),
            }
            for d in raw
        ]

    def scheduled_on(self, day: date) -> list[dict[str, Any]]:
        """Workouts on the calendar for one date, past or future.

        `upcoming_workouts` deliberately looks forward only; reviewing a session
        means asking what was prescribed for a day that has already happened.
        """
        # One month is enough: the calendar payload for a month contains every
        # entry dated within it. `calendarItems` also carries completed
        # activities, hence the itemType filter.
        sched = self._login().get_scheduled_workouts(day.year, day.month) or {}
        iso = day.isoformat()
        out: list[dict[str, Any]] = []
        for it in sched.get("calendarItems") or []:
            if it.get("itemType") != "workout" or it.get("date") != iso:
                continue
            out.append({
                "date": it.get("date"),
                "scheduled_id": it.get("id"),
                "workout_id": it.get("workoutId"),
                "title": it.get("title"),
                "sport": it.get("sportTypeKey"),
                "atp_plan_id": it.get("atpPlanId"),
            })
        return out

    def heart_rate_zones(self) -> dict[str, Any] | None:
        """The athlete's configured max HR and zone floors, straight from Garmin.

        Far better than inferring max from recent efforts: someone training
        deliberately easy for months never approaches their max, so history
        under-reads. This is the same configuration the watch itself uses.

        Returns None when the account has no zone setup, or the numbers are
        obviously unusable — callers fall back to estimating from history.
        """
        try:
            raw = self._login().get_heart_rate_zones()
        except Exception as exc:  # pragma: no cover - upstream flakiness
            logger.warning("garmin: could not read heart rate zones (%s)", exc)
            return None

        # The API returns a list, one entry per sport; DEFAULT is the running one.
        if isinstance(raw, list):
            entry = next(
                (z for z in raw if (z or {}).get("sport") == "DEFAULT"),
                raw[0] if raw else None,
            )
        else:
            entry = raw
        if not entry:
            return None

        max_hr = entry.get("maxHeartRateUsed")
        if max_hr is None or not 120 <= float(max_hr) <= 230:
            return None

        floors = [entry.get(f"zone{i}Floor") for i in range(1, 6)]
        return {
            "max_hr": int(max_hr),
            "resting_hr": entry.get("restingHeartRateUsed"),
            "lactate_threshold_hr": entry.get("lactateThresholdHeartRateUsed"),
            "training_method": entry.get("trainingMethod"),
            # None when a zone is unset — the planner treats a partial ladder as absent.
            "zone_floors": [int(f) for f in floors] if all(f is not None for f in floors) else None,
        }

    # ---------- WRITE ----------
    def create_running_workout(
        self, spec: dict[str, Any], _build_only: bool = False
    ) -> Any:
        """spec = {name, estimated_duration_s?, steps: [{kind, duration_s?, iterations?, target?, steps?}]}.

        `_build_only` returns the assembled workout instead of uploading it, so
        `update_running_workout` can reuse the exact same construction.
        """
        from garminconnect.workout import (
            ConditionType,
            ExecutableStep,
            RunningWorkout,
            StepType,
            TargetType,
            WorkoutSegment,
            create_warmup_step,
            create_interval_step,
            create_recovery_step,
            create_cooldown_step,
            create_repeat_group,
        )

        # (stepTypeId, key, displayOrder) exactly as the library's own helpers
        # emit them — Garmin is order-sensitive about these dicts.
        step_types = {
            "warmup": (StepType.WARMUP, "warmup", 1),
            "cooldown": (StepType.COOLDOWN, "cooldown", 2),
            "interval": (StepType.INTERVAL, "interval", 3),
            "recovery": (StepType.RECOVERY, "recovery", 4),
        }

        def distance_step(
            kind: str, metres: float, order: int, target_type: dict[str, Any] | None
        ) -> Any:
            """A step that ends after a distance.

            The library ships `create_distance_interval_step` and nothing for the
            other kinds, so this builds them — same shape, different stepType.
            """
            type_id, key, display = step_types[kind]
            return ExecutableStep(
                stepOrder=order,
                stepType={
                    "stepTypeId": type_id,
                    "stepTypeKey": key,
                    "displayOrder": display,
                },
                endCondition={
                    "conditionTypeId": ConditionType.DISTANCE,
                    "conditionTypeKey": "distance",
                    "displayOrder": 3,
                    "displayable": True,
                },
                endConditionValue=float(metres),
                targetType=target_type
                or {
                    "workoutTargetTypeId": TargetType.NO_TARGET,
                    "workoutTargetTypeKey": "no.target",
                    "displayOrder": 1,
                },
            )

        sport = {"sportTypeId": 1, "sportTypeKey": "running"}

        def build_target(
            t: dict[str, Any] | None,
        ) -> tuple[dict[str, Any], float, float] | None:
            """Split a target into (type descriptor, low, high).

            `targetType` carries only the *kind* of target. The bounds are
            `targetValueOne`/`targetValueTwo` on the step itself — put them
            inside `targetType` and Garmin silently drops them, which shows up
            on the watch as a pace range of 0:00–0:00.
            """
            if not t:
                return None
            kind = t.get("type")
            if kind == "pace":
                return (
                    {
                        "workoutTargetTypeId": 6,
                        "workoutTargetTypeKey": "pace.zone",
                        "displayOrder": 1,
                    },
                    float(t["low_mps"]),
                    float(t["high_mps"]),
                )
            if kind == "hr":
                return (
                    {
                        "workoutTargetTypeId": 4,
                        "workoutTargetTypeKey": "heart.rate.zone",
                        "displayOrder": 1,
                    },
                    float(t["low_bpm"]),
                    float(t["high_bpm"]),
                )
            return None

        def build_step(s: dict[str, Any], order: int) -> Any:
            kind = s["kind"]
            if kind == "repeat":
                inner = [build_step(ss, i + 1) for i, ss in enumerate(s.get("steps", []))]
                return create_repeat_group(int(s.get("iterations", 1)), inner, step_order=order)
            dur = float(s.get("duration_s") or 0)
            metres = float(s.get("distance_m") or 0)
            tgt = build_target(s.get("target"))
            type_dict = tgt[0] if tgt else None

            if kind not in step_types:
                raise ValueError(f"Unknown step kind: {kind}")
            if metres > 0:
                step = distance_step(kind, metres, order, type_dict)
            elif kind == "warmup":
                step = create_warmup_step(dur, step_order=order, target_type=type_dict)
            elif kind == "interval":
                step = create_interval_step(dur, step_order=order, target_type=type_dict)
            elif kind == "recovery":
                step = create_recovery_step(dur, step_order=order, target_type=type_dict)
            else:
                step = create_cooldown_step(dur, step_order=order, target_type=type_dict)

            if tgt:
                # Garmin wants the slower/lower bound first for both target kinds.
                _type, low, high = tgt
                step.targetValueOne = min(low, high)
                step.targetValueTwo = max(low, high)
            return step

        steps = [build_step(s, i + 1) for i, s in enumerate(spec["steps"])]
        workout = RunningWorkout(
            workoutName=spec["name"],
            estimatedDurationInSecs=int(spec.get("estimated_duration_s") or 0),
            workoutSegments=[
                WorkoutSegment(
                    segmentOrder=1,
                    sportType=sport,
                    workoutSteps=steps,
                )
            ],
        )
        if _build_only:
            return workout
        result = self._login().upload_running_workout(workout)
        return {"workout_id": result.get("workoutId"), "raw": result}

    def update_running_workout(
        self, workout_id: int | str, spec: dict[str, Any]
    ) -> dict[str, Any]:
        """Replace an existing template's contents, keeping its id.

        Garmin's endpoint is a whole-workout PUT, so the spec must be complete —
        this is not a patch. Keeping the id is the point: every calendar entry
        already pointing at this workout picks up the change, which is why
        editing beats delete-and-recreate for a plan that is already scheduled.
        """
        workout = self.create_running_workout(spec, _build_only=True)
        body = workout.model_dump(exclude_none=True)
        result = self._login().update_workout(int(workout_id), body)
        return {"workout_id": int(workout_id), "raw": result}

    def create_strength_workout(self, spec: dict[str, Any]) -> dict[str, Any]:
        """spec = {name, exercises: [{category, exercise_name?, sets, reps, rest_s, weight_kg?}]}.

        Each exercise becomes one repeat group — the "N Sets" block the Garmin
        editor shows — so the watch counts sets and rests for you. `category` must
        be one of `garminconnect.exercises.CATEGORIES`; `exercise_name` narrows it
        to a variant and is validated against the catalogue, because a bad name
        uploads cleanly and then shows as a blank exercise on the device.
        """
        from garminconnect.exercises import BY_NAME, CATEGORIES, EXERCISES
        from garminconnect.workout import (
            ConditionType,
            ExecutableStep,
            StepType,
            StrengthWorkout,
            TargetType,
            WorkoutSegment,
            create_strength_set,
        )

        # The catalogue keys entries by display name ("Barbell Bench Press") and
        # carries the key Garmin actually wants ("BARBELL_BENCH_PRESS"). Accept
        # either spelling and resolve, because an unrecognised name uploads
        # cleanly and then shows as a blank exercise on the watch.
        by_key = {e["exercise"]: e for e in EXERCISES}

        def resolve(raw: str, override: str | None = None) -> tuple[str, str]:
            """(category, exercise key) for a display name or key."""
            raw = (raw or "").strip()
            entry = BY_NAME.get(raw) or by_key.get(raw.upper().replace(" ", "_"))
            if raw and entry is None:
                raise ValueError(
                    f"unknown exercise {raw!r} — use a display name from "
                    f"garminconnect.exercises, e.g. 'Barbell Bench Press'"
                )
            category = str(override or (entry or {}).get("category") or "").upper()
            if category not in CATEGORIES:
                raise ValueError(
                    f"unknown exercise category {category!r} — "
                    f"see garminconnect.exercises.CATEGORIES"
                )
            return category, (entry or {}).get("exercise", "")

        steps = []
        order = 1

        # An optional machine warm-up, held on *time* rather than reps. The
        # strength builders are all rep-based, so this step is assembled here —
        # `ExecutableStep` allows extras, which is how the exercise category
        # rides along with a timed step.
        warm = spec.get("warmup")
        if warm:
            category, name = resolve(
                str(warm.get("exercise_name") or ""), warm.get("category")
            )
            steps.append(
                ExecutableStep(
                    stepOrder=order,
                    stepType={
                        "stepTypeId": StepType.WARMUP,
                        "stepTypeKey": "warmup",
                        "displayOrder": 1,
                    },
                    endCondition={
                        "conditionTypeId": ConditionType.TIME,
                        "conditionTypeKey": "time",
                        "displayOrder": 2,
                        "displayable": True,
                    },
                    endConditionValue=float(warm.get("duration_s") or 600),
                    targetType={
                        "workoutTargetTypeId": TargetType.NO_TARGET,
                        "workoutTargetTypeKey": "no.target",
                        "displayOrder": 1,
                    },
                    category=category,
                    exerciseName=name,
                )
            )
            order += 1

        for ex in spec.get("exercises") or []:
            category, name = resolve(
                str(ex.get("exercise_name") or ""), ex.get("category")
            )
            steps.append(
                create_strength_set(
                    category,
                    step_order=order,
                    sets=int(ex.get("sets") or 3),
                    reps=int(ex.get("reps") or 10),
                    rest_seconds=float(ex.get("rest_s") or 90),
                    exercise_name=name,
                    weight_kg=ex.get("weight_kg"),
                )
            )
            # The group takes `order`, its exercise and rest steps the next two.
            order += 3

        if not steps:
            raise ValueError("a strength workout needs at least one exercise")

        workout = StrengthWorkout(
            workoutName=str(spec.get("name") or "Strength")[:100],
            estimatedDurationInSecs=int(spec.get("estimated_duration_s") or 0),
            workoutSegments=[
                WorkoutSegment(
                    segmentOrder=1,
                    sportType={"sportTypeId": 5, "sportTypeKey": "strength_training"},
                    workoutSteps=steps,
                )
            ],
        )
        r = self._login().upload_strength_workout(workout)
        return {"workout_id": (r or {}).get("workoutId"), "raw": r}

    def schedule_workout(self, workout_id: int | str, day: date) -> dict[str, Any]:
        r = self._login().schedule_workout(int(workout_id), day.isoformat())
        return {"scheduled_id": (r or {}).get("id"), "raw": r}

    def delete_workout(self, workout_id: int | str) -> dict[str, Any] | None:
        return {"result": self._login().delete_workout(int(workout_id))}

    def unschedule_workout(self, scheduled_id: int | str) -> dict[str, Any] | None:
        return {"result": self._login().unschedule_workout(int(scheduled_id))}

    def push_workout_to_device(
        self, workout_id: int | str, device_id: int | str | None = None
    ) -> dict[str, Any]:
        r = self._login().push_workout_to_device(int(workout_id), device_id)
        return {"result": r}

    # ---------- helpers ----------
    @staticmethod
    def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
        if step.get("workoutSteps"):
            return {
                "kind": "repeat",
                "iterations": step.get("numberOfIterations"),
                "steps": [GarminProvider._normalize_step(s) for s in step["workoutSteps"]],
            }
        return {
            "kind": (step.get("stepType") or {}).get("stepTypeKey"),
            "end_condition": (step.get("endCondition") or {}).get("conditionTypeKey"),
            "end_value": step.get("endConditionValue"),
            "target_type": (step.get("targetType") or {}).get("workoutTargetTypeKey"),
            "target_low": step.get("targetValueOne"),
            "target_high": step.get("targetValueTwo"),
            "zone": step.get("zoneNumber"),
        }


GarminAuthError = GarminConnectAuthenticationError
GarminConnError = GarminConnectConnectionError

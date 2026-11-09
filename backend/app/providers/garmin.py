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

#: Above this, a temperature reading cannot be Celsius for real-world weather,
#: so the payload must be Fahrenheit. Deliberately well clear of the hottest
#: inhabited places: the cost of guessing Celsius wrongly is a nonsense figure
#: on the page, and the cost of guessing Fahrenheit wrongly is the same.
PLAUSIBLE_MAX_CELSIUS = 45.0

#: Garmin reports wind in mph on an imperial account, km/h on a metric one.
MILES_TO_KM = 1.609344


def normalize_weather(weather: dict[str, Any]) -> dict[str, Any]:
    """One reading in metric, with the account's unit inferred once.

    Garmin reports weather in whatever unit system the account is set to and
    names no unit anywhere in the payload, so it has to be inferred. The
    inference has to be made **once for the whole reading**, never per field:
    the unit is a single account-level setting, so a reading is wholly imperial
    or wholly metric. Temperature and wind are normalised together off that one
    decision, which is why they share a function rather than each having their
    own — two decisions are two chances to disagree.

    Deciding per value splits one reading across both scales as soon as one
    field crosses the threshold and another does not, which is how this was
    found — 46F/43F/43F came back as 7.8 C beside a literal 43 C "feels like",
    on a 7 C London morning.

    **Only `temp` votes**, with `apparentTemp` as a fallback when `temp` is
    absent. Two fields that look like evidence are not:

    * `dewPoint` carries none. Dew point is never above air temperature, so a
      Fahrenheit `dewPoint` over the threshold implies `temp` is over it too and
      `temp` has already decided. All it can do is harm — a sentinel or a bogus
      value on an otherwise Celsius reading would convert a correct 18 C into
      -7.8 C.
    * `apparentTemp` is a heat index, and on a hot humid day a genuinely Celsius
      account reports a feels-like above the threshold with the air temperature
      below it (38 C air, ~50 C apparent). Letting it vote would convert the
      whole reading and turn that 38 C into 3 C.

    **`windSpeed` rides on the same decision and cannot vote on it.** Garmin
    reports it in mph on a Fahrenheit account and km/h on a Celsius one, and it
    was previously mapped straight to `wind_kph` — so an imperial account's
    figure was mph under a metric label, reading 38% low. Wind speed carries no
    usable evidence of its own: 6 and 20 are ordinary readings in either unit,
    so there is no threshold to test. It has to follow the temperature.

    Residual limit: a genuinely cold Fahrenheit reading whose `temp` sits below
    the threshold is indistinguishable from Celsius, and the whole reading —
    wind included — stays unconverted. Only the account's own unit setting could
    settle that, and it is not in this payload.
    """
    # `temp` alone, because it is the only field that is unambiguously the air
    # temperature; apparent temperature is a heat index and can exceed the
    # threshold in Celsius. See the docstring for why dew point and wind are
    # not read.
    deciding = weather.get("temp")
    if deciding is None:
        deciding = weather.get("apparentTemp")
    imperial = deciding is not None and float(deciding) > PLAUSIBLE_MAX_CELSIUS

    def to_c(v: float | None) -> float | None:
        if v is None:
            return None
        return (float(v) - 32) * 5 / 9 if imperial else float(v)

    wind = weather.get("windSpeed")
    return {
        "temp_c": to_c(weather.get("temp")),
        "apparent_c": to_c(weather.get("apparentTemp")),
        "humidity": weather.get("relativeHumidity"),
        "wind_kph": (
            round(float(wind) * MILES_TO_KM, 1)
            if wind is not None and imperial
            else wind
        ),
        "conditions": (weather.get("weatherTypeDTO") or {}).get("desc"),
    }

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

        weather_out = normalize_weather(weather) if weather else {}

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

    # ---------- TRAINING METRICS ----------
    @staticmethod
    def _latest_device_entry(by_device: dict[str, Any] | None) -> dict[str, Any]:
        """Garmin keys several metrics by the device that computed them.

        An account with more than one watch gets one entry per device, and the
        one that matters is whichever has the freshest `calendarDate` — the
        primary-training-device flag is not always set.
        """
        entries = [e for e in (by_device or {}).values() if isinstance(e, dict)]
        if not entries:
            return {}
        return max(entries, key=lambda e: str(e.get("calendarDate") or ""))

    def athlete_profile(self) -> dict[str, Any]:
        raw = (self._login().get_user_profile() or {}).get("userData") or {}
        weight_g = raw.get("weight")
        return {
            "height_cm": raw.get("height"),
            "weight_kg": round(float(weight_g) / 1000.0, 1) if weight_g else None,
            "birth_date": raw.get("birthDate"),
            "gender": raw.get("gender"),
        }

    def training_status(self, day: date) -> dict[str, Any]:
        raw = self._login().get_training_status(day.isoformat()) or {}
        vo2 = (raw.get("mostRecentVO2Max") or {}).get("generic") or {}
        bal = self._latest_device_entry(
            (raw.get("mostRecentTrainingLoadBalance") or {}).get(
                "metricsTrainingLoadBalanceDTOMap"
            )
        )
        status = self._latest_device_entry(
            (raw.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData")
        )
        # Acute/chronic load is nested one level down, not on the status entry.
        acute = status.get("acuteTrainingLoadDTO") or {}
        buckets = [
            ("aerobic_low", "monthlyLoadAerobicLow", "monthlyLoadAerobicLowTarget"),
            ("aerobic_high", "monthlyLoadAerobicHigh", "monthlyLoadAerobicHighTarget"),
            ("anaerobic", "monthlyLoadAnaerobic", "monthlyLoadAnaerobicTarget"),
        ]
        return {
            "date": day.isoformat(),
            # The precise value is what the watch shows; vo2MaxValue is rounded.
            "vo2max": vo2.get("vo2MaxPreciseValue") or vo2.get("vo2MaxValue"),
            "vo2max_measured": vo2.get("calendarDate"),
            # `trainingStatus` is an opaque integer code; the feedback phrase is
            # the part that means anything, so both travel together.
            "status": status.get("trainingStatus"),
            "feedback": status.get("trainingStatusFeedbackPhrase"),
            "acute_load": acute.get("dailyTrainingLoadAcute"),
            "chronic_load": acute.get("dailyTrainingLoadChronic"),
            "acwr": acute.get("dailyAcuteChronicWorkloadRatio"),
            "acwr_status": acute.get("acwrStatus"),
            "balance_feedback": bal.get("trainingBalanceFeedbackPhrase"),
            "load_balance": [
                {
                    "bucket": name,
                    "load": bal.get(load_key),
                    "target_min": bal.get(target_key + "Min"),
                    "target_max": bal.get(target_key + "Max"),
                }
                for name, load_key, target_key in buckets
                if bal.get(load_key) is not None
            ],
        }

    def hrv(self, day: date) -> dict[str, Any]:
        raw = (self._login().get_hrv_data(day.isoformat()) or {}).get("hrvSummary") or {}
        base = raw.get("baseline") or {}
        return {
            "date": raw.get("calendarDate") or day.isoformat(),
            "weekly_avg": raw.get("weeklyAvg"),
            "last_night": raw.get("lastNightAvg"),
            "status": raw.get("status"),
            "feedback": raw.get("feedbackPhrase"),
            "baseline_low_upper": base.get("lowUpper"),
            "baseline_balanced_low": base.get("balancedLow"),
            "baseline_balanced_high": base.get("balancedUpper"),
        }

    def training_readiness(self, day: date) -> dict[str, Any]:
        raw = self._login().get_training_readiness(day.isoformat()) or []
        if isinstance(raw, dict):
            raw = [raw]
        readings = sorted(
            (r for r in raw if isinstance(r, dict)),
            key=lambda r: str(r.get("timestamp") or ""),
        )
        if not readings:
            return {"date": day.isoformat(), "score": None, "factors": []}

        # Garmin rewrites readiness several times a day, and the score collapses
        # right after a session: one hard run took this account from 70 to 22 with
        # a 46-hour recovery time. That reading says the run was hard, not that the
        # athlete is unready, so the figure worth reporting is the wake-up reset.
        # The midnight reading is no good either — it lands before sleep is scored
        # (`validSleep` false, no sleep score at all).
        chosen = next(
            (r for r in readings if r.get("inputContext") == "AFTER_WAKEUP_RESET"),
            next((r for r in reversed(readings) if r.get("validSleep")), readings[-1]),
        )
        factors = [
            ("recovery_time", "recoveryTimeFactorPercent", "recoveryTimeFactorFeedback"),
            ("hrv", "hrvFactorPercent", "hrvFactorFeedback"),
            ("stress_history", "stressHistoryFactorPercent", "stressHistoryFactorFeedback"),
            ("sleep_score", "sleepScoreFactorPercent", "sleepScoreFactorFeedback"),
            ("sleep_history", "sleepHistoryFactorPercent", "sleepHistoryFactorFeedback"),
            ("acwr", "acwrFactorPercent", "acwrFactorFeedback"),
        ]
        return {
            "date": chosen.get("calendarDate") or day.isoformat(),
            "score": chosen.get("score"),
            "level": chosen.get("level"),
            "feedback": chosen.get("feedbackShort"),
            "measured_at": chosen.get("timestampLocal") or chosen.get("timestamp"),
            "context": chosen.get("inputContext"),
            "sleep_score": chosen.get("sleepScore"),
            "recovery_time_min": chosen.get("recoveryTime"),
            "acute_load": chosen.get("acuteLoad"),
            # The post-exercise reading still earns its place: it is how long the
            # watch thinks today's session needs to be absorbed.
            "latest_score": readings[-1].get("score"),
            "latest_recovery_time_min": readings[-1].get("recoveryTime"),
            "factors": [
                {"factor": name, "percent": chosen.get(pct), "feedback": chosen.get(fb)}
                for name, pct, fb in factors
                if chosen.get(pct) is not None
            ],
        }

    def fitness_age(self, day: date) -> dict[str, Any]:
        raw = self._login().get_fitnessage_data(day.isoformat()) or {}
        comps = raw.get("components") or {}
        return {
            "date": day.isoformat(),
            "chronological": raw.get("chronologicalAge"),
            "fitness": raw.get("fitnessAge"),
            "achievable": raw.get("achievableFitnessAge"),
            "updated": raw.get("lastUpdated"),
            "components": [
                {
                    "name": name,
                    "value": (c or {}).get("value"),
                    "target_value": (c or {}).get("targetValue"),
                    "improvement_value": (c or {}).get("improvementValue"),
                    "potential_age": (c or {}).get("potentialAge"),
                    # 1 is the component holding the fitness age back hardest.
                    "priority": (c or {}).get("priority"),
                }
                for name, c in sorted(comps.items())
            ],
        }

    def race_predictions(self) -> dict[str, Any]:
        raw = self._login().get_race_predictions() or {}
        return {
            "date": raw.get("calendarDate"),
            "time_5k_s": raw.get("time5K"),
            "time_10k_s": raw.get("time10K"),
            "time_half_s": raw.get("timeHalfMarathon"),
            "time_marathon_s": raw.get("timeMarathon"),
        }

    def weight_history(self, start: date, end: date) -> list[dict[str, Any]]:
        raw = self._login().get_body_composition(start.isoformat(), end.isoformat()) or {}
        out: dict[str, float] = {}
        for entry in raw.get("dateWeightList") or []:
            day = entry.get("calendarDate")
            grams = entry.get("weight")
            if not day or not grams:
                continue
            # Several weigh-ins on one day happen; keep the first (the morning one).
            out.setdefault(day, round(float(grams) / 1000.0, 1))
        return [{"day": d, "weight_kg": kg} for d, kg in sorted(out.items())]

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

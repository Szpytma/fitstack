"""FitStack MCP server.

Runs over stdio and exposes Garmin data as tools for any MCP client
(Claude Code, Claude Desktop, etc.). Uses the same cached Garmin tokens
as the FastAPI backend — never accepts a password.

Launch:
    python -m app.mcp_server
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from mcp.server import MCPServer

from app import active_plan, history
from app.config import settings
from app.planner import PlanInput, build_plan
from app.providers.garmin import GarminProvider
from app.schemas.plan import parse_goal_time

mcp = MCPServer(name="fitstack", version="0.3.0")
_provider = GarminProvider(settings.garmin_tokenstore)


def _require_auth() -> None:
    if not _provider.is_available():
        raise RuntimeError(
            "Garmin is not authenticated. Run python-garminconnect's example.py to "
            f"create tokens at {settings.garmin_tokenstore}."
        )


def _parse_day(day: str | None, default: date) -> date:
    return date.fromisoformat(day) if day else default


# ---------- READ tools ----------

@mcp.tool()
def get_daily_summary(day: str | None = None) -> dict[str, Any]:
    """Steps, calories, distance, resting/min/max HR for a day.

    Args:
        day: YYYY-MM-DD. Defaults to today.
    """
    _require_auth()
    return _provider.daily_summary(_parse_day(day, date.today()))


@mcp.tool()
def get_daily_summaries(days: int = 14) -> list[dict[str, Any]]:
    """Daily summary history for the last N days, newest first."""
    _require_auth()
    out: list[dict[str, Any]] = []
    today = date.today()
    for i in range(days):
        d = today - timedelta(days=i)
        try:
            out.append(_provider.daily_summary(d))
        except Exception as e:
            out.append({"date": d.isoformat(), "error": str(e)})
    return out


@mcp.tool()
def get_recent_activities(limit: int = 30) -> list[dict[str, Any]]:
    """List of recent activities (runs, rides, walks, etc.), newest first.

    Each item includes activity_id, name, type, start time, duration, distance,
    average and max HR, calories, average speed, and elevation gain.
    """
    _require_auth()
    return _provider.activities(limit=limit)


@mcp.tool()
def get_activity_detail(activity_id: int) -> dict[str, Any]:
    """Full detail for one activity.

    Includes time-series (HR, pace, elevation, GPS), splits, HR zones, and weather.
    Use this after get_recent_activities to drill into a specific run.
    """
    _require_auth()
    return _provider.activity_detail(activity_id)


@mcp.tool()
def get_sleep(day: str | None = None) -> dict[str, Any]:
    """Sleep summary (total, deep/light/REM/awake seconds, score) for a night.

    Args:
        day: YYYY-MM-DD of the wake day. Defaults to yesterday.
    """
    _require_auth()
    return _provider.sleep(_parse_day(day, date.today() - timedelta(days=1)))


@mcp.tool()
def get_sleep_history(days: int = 14) -> list[dict[str, Any]]:
    """Sleep history for the last N nights, newest first."""
    _require_auth()
    out: list[dict[str, Any]] = []
    today = date.today()
    for i in range(1, days + 1):
        d = today - timedelta(days=i)
        try:
            out.append(_provider.sleep(d))
        except Exception as e:
            out.append({"date": d.isoformat(), "error": str(e)})
    return out


@mcp.tool()
def get_upcoming_workouts(days_ahead: int = 14) -> list[dict[str, Any]]:
    """Upcoming scheduled workouts (from Garmin Coach or manually scheduled)."""
    _require_auth()
    return _provider.upcoming_workouts(days_ahead=days_ahead)


@mcp.tool()
def get_workout_detail(workout_id: int) -> dict[str, Any]:
    """Full step-by-step detail for a workout template."""
    _require_auth()
    return _provider.workout_detail(workout_id)


@mcp.tool()
def list_workout_templates(limit: int = 100) -> list[dict[str, Any]]:
    """List of workout templates saved in Garmin Connect."""
    _require_auth()
    return _provider.list_workouts(limit=limit)


@mcp.tool()
def list_devices() -> list[dict[str, Any]]:
    """Registered Garmin devices, needed as targets for push_workout_to_device."""
    _require_auth()
    return _provider.list_devices()


@mcp.tool()
def generate_race_plan(
    race_km: float,
    race_date: str,
    runs_per_week: int = 4,
    long_run_day: str = "Sunday",
    weekly_km: float | None = None,
    goal_time: str | None = None,
    race_name: str | None = None,
    target_mode: str = "pace",
) -> dict[str, Any]:
    """Build a periodised race training plan from the athlete's own Garmin history.

    Deterministic — no guessing at paces. Threshold speed is derived from the goal
    time if given, otherwise from the best recent run normalised to a 10K
    equivalent via Riegel. Returns week-by-week sessions, each carrying a `spec`
    ready for create_running_workout, plus a `basis` explaining where the paces
    came from and `warnings` for anything questionable.

    Prefer this over inventing a plan yourself: it keeps volume progression,
    down weeks and taper consistent, and its paces trace back to real runs.
    Nothing is written to Garmin — use create_running_workout + schedule_workout
    on the returned specs once the user has approved the plan.

    Args:
        race_km: Race distance in km (5, 10, 21.0975, 42.195, ...).
        race_date: YYYY-MM-DD.
        runs_per_week: 2-7.
        long_run_day: Weekday name, e.g. "Sunday".
        weekly_km: Current weekly volume. Read from recent activities if omitted.
        goal_time: "1:45:00" or "45:00". Omit to plan off current fitness.
        race_name: Optional label for the race.
        target_mode: "pace" (default) or "hr" to target every session by heart
            rate instead. HR bands come from the athlete's configured Garmin
            zones, falling back to an estimate from recent runs.
    """
    _require_auth()
    try:
        activities = _provider.activities(limit=60)
        history.attach_laps(_provider, activities)
    except Exception:
        activities = []

    hr_zones = None
    if target_mode == "hr":
        try:
            hr_zones = _provider.heart_rate_zones()
        except Exception:
            hr_zones = None

    return build_plan(
        PlanInput(
            race_km=race_km,
            race_date=date.fromisoformat(race_date),
            runs_per_week=runs_per_week,
            long_run_day=long_run_day,
            weekly_km=weekly_km,
            goal_time_s=parse_goal_time(goal_time) if goal_time else None,
            race_name=race_name,
            target_mode=target_mode,
        ),
        activities,
        hr_zones,
    )


# ---------- Rolling weekly plan ----------
#
# A race block delivered one week at a time, Garmin-Coach style. Nothing here
# touches Garmin: these read history and write only the local plan anchor. The
# returned sessions still carry a `spec`, so scheduling them goes through
# create_running_workout + schedule_workout with the usual confirmation.


def _plan_context(target_mode: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Recent runs, plus HR zones when targeting by heart rate."""
    try:
        activities = _provider.activities(limit=60)
        history.attach_laps(_provider, activities)
    except Exception:
        activities = []

    # Always read zones: max HR is what makes the efficiency factor comparable,
    # and adaptation needs it whatever the session targets are.
    hr_zones = None
    try:
        hr_zones = _provider.heart_rate_zones()
    except Exception:
        hr_zones = None
    return activities, hr_zones


@mcp.tool()
def start_training_plan(
    race_km: float,
    race_date: str,
    runs_per_week: int = 4,
    long_run_day: str = "Sunday",
    weekly_km: float | None = None,
    goal_time: str | None = None,
    race_name: str | None = None,
    target_mode: str = "pace",
) -> dict[str, Any]:
    """Start a rolling plan and return only its first week.

    Use this instead of generate_race_plan when the athlete wants the plan fed to
    them a week at a time rather than a whole block up front. The full periodised
    block is still computed — base/build/peak/taper, down weeks, taper — but only
    the current week is handed back, and each later week is regenerated against
    fresh Garmin history when asked for.

    Two things are pinned so the periodisation survives regeneration: the start
    date (so the phase arc advances instead of restarting at "base") and the
    week-one volume (so the ramp does not drift with a sick or heavy week). Paces
    are deliberately not pinned — they re-derive from recent runs every week.

    Replaces any plan already running. Writes nothing to Garmin.

    Args:
        race_km: Race distance in km (5, 10, 21.0975, 42.195, ...).
        race_date: YYYY-MM-DD.
        runs_per_week: 2-7.
        long_run_day: Weekday name, e.g. "Sunday".
        weekly_km: Current weekly volume. Read from recent activities if omitted.
        goal_time: "1:45:00" or "45:00". Omit to plan off current fitness.
        race_name: Optional label for the race.
        target_mode: "pace" (default) or "hr".
    """
    _require_auth()
    activities, hr_zones = _plan_context(target_mode)

    parsed_race_date = date.fromisoformat(race_date)
    today = date.today()

    full = build_plan(
        PlanInput(
            race_km=race_km,
            race_date=parsed_race_date,
            runs_per_week=runs_per_week,
            long_run_day=long_run_day,
            weekly_km=weekly_km,
            goal_time_s=parse_goal_time(goal_time) if goal_time else None,
            race_name=race_name,
            start_date=today,
            target_mode=target_mode,
        ),
        activities,
        hr_zones,
    )

    plan = active_plan.ActivePlan(
        race_km=race_km,
        race_date=parsed_race_date,
        start_date=today,
        anchor_weekly_km=active_plan.anchor_from_plan(full),
        runs_per_week=runs_per_week,
        long_run_day=long_run_day,
        goal_time_s=parse_goal_time(goal_time) if goal_time else None,
        race_name=race_name,
        target_mode=target_mode,
        original=full,
    )
    active_plan.save(plan)

    # The block's own first week, which may start before the next Monday when the
    # plan is begun midweek — hand back that one rather than skipping it.
    first_start = date.fromisoformat(full["weeks"][0]["start"])
    week_start = min(first_start, active_plan.upcoming_week_start(today))
    if active_plan.select_week(full, week_start) is None:
        week_start = first_start
    return active_plan.week_view(plan, full, week_start, activities)


@mcp.tool()
def get_training_week(week_offset: int = 0) -> dict[str, Any]:
    """The next week of the running plan, adapted to how the last ones went.

    Ask for this after finishing the week's long run. Returns the week starting on
    the Monday on or after today; week_offset=-1 gives the week already in
    progress, a positive number looks further ahead.

    Three things happen on every call. Paces re-derive from recent runs, so they
    track fitness. Phase and the volume ramp follow the block fixed at the start.
    And the week is checked against what actually happened: two consecutive weeks
    under 70% of plan hold the volume instead of climbing, two with no runs at all
    step it back, and two where efficiency (metres per minute per heartbeat) sat
    below baseline hold it too — the same work costing more heartbeats.

    `decision` carries the action, the multiplier and the reasoning; `last_week`
    and `original_planned_km` show what was asked for versus what was delivered.
    The rules are deterministic (backend/app/adapt.py) so the same history always
    gives the same week. Deliberately conservative: one bad week never moves it.

    If the athlete tells you something the data cannot show — illness, travel, a
    niggle, a race they slotted in — that is yours to weigh, not the planner's.
    Say so explicitly rather than silently overriding the numbers.

    Args:
        week_offset: Weeks to shift from the upcoming one. 0 = next week.
    """
    _require_auth()
    plan = active_plan.require()
    activities, hr_zones = _plan_context(plan.target_mode)
    week_start = active_plan.upcoming_week_start(offset=week_offset)
    return active_plan.adapted_view(plan, activities, hr_zones, week_start)


@mcp.tool()
def get_training_plan_status() -> dict[str, Any] | None:
    """The running plan's race, dates and position in the block, or None if none."""
    plan = active_plan.load()
    return active_plan.status(plan) if plan else None


@mcp.tool()
def end_training_plan() -> dict[str, Any]:
    """Stop the rolling plan. Leaves any already-scheduled Garmin workouts alone."""
    return {"cleared": active_plan.clear()}


# ---------- WRITE tools (confirm with the user before calling) ----------

@mcp.tool()
def create_running_workout(spec: dict[str, Any]) -> dict[str, Any]:
    """Create a running workout template in Garmin Connect.

    spec = {
        "name": str,
        "estimated_duration_s": int | None,
        "steps": [step, ...],
    }
    step = {
        "kind": "warmup" | "interval" | "recovery" | "cooldown" | "repeat",
        "duration_s": float | None,          # for non-repeat kinds
        "iterations": int | None,             # for kind=repeat
        "steps": [step, ...] | None,          # for kind=repeat
        "target": target | None,
    }
    target = {"type": "pace", "low_mps": float, "high_mps": float}
          or {"type": "hr", "low_bpm": int, "high_bpm": int}
    """
    _require_auth()
    return _provider.create_running_workout(spec)


@mcp.tool()
def update_running_workout(workout_id: int, spec: dict[str, Any]) -> dict[str, Any]:
    """Replace an existing running workout template in place, keeping its id.

    Use this to retarget a workout the athlete has already been given — raise or
    lower a heart-rate band, change durations, adjust reps — without disturbing
    the calendar. Every date already scheduled against this workout picks up the
    change, which delete-and-recreate would break.

    `spec` is the same shape as create_running_workout and must be COMPLETE:
    Garmin replaces the whole workout, so any step omitted is deleted. Read the
    current structure with get_workout_detail first if you are editing rather
    than rewriting.
    """
    _require_auth()
    return _provider.update_running_workout(workout_id, spec)


@mcp.tool()
def schedule_workout(workout_id: int, day: str) -> dict[str, Any]:
    """Schedule an existing workout template on a date (YYYY-MM-DD)."""
    _require_auth()
    return _provider.schedule_workout(workout_id, date.fromisoformat(day))


@mcp.tool()
def unschedule_workout(scheduled_id: int) -> dict[str, Any] | None:
    """Remove a scheduled instance of a workout (does NOT delete the template)."""
    _require_auth()
    return _provider.unschedule_workout(scheduled_id)


@mcp.tool()
def delete_workout(workout_id: int) -> dict[str, Any] | None:
    """Permanently delete a workout template."""
    _require_auth()
    return _provider.delete_workout(workout_id)


@mcp.tool()
def push_workout_to_device(workout_id: int, device_id: int | None = None) -> dict[str, Any]:
    """Push a workout template to a Garmin device (default: primary device)."""
    _require_auth()
    return _provider.push_workout_to_device(workout_id, device_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

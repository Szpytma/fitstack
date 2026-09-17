"""Judge a completed activity against the workout that was prescribed for it.

No stored feedback, and no asking the athlete how it felt: the evidence is
already in Garmin. What was prescribed is in the workout template; what actually
happened is in the activity's time series. The gap between them is the verdict.

Pure functions — everything here takes plain dicts so the judgement can be
exercised without touching the network.
"""

from __future__ import annotations

from typing import Any, Literal

Verdict = Literal["too_hard", "about_right", "too_easy", "unknown"]

# How far outside the prescribed band counts as a real miss rather than noise.
# HR wanders a few beats from pacing, terrain and drift; below this it is not
# evidence of anything.
HR_TOLERANCE_BPM = 5.0
PACE_TOLERANCE_MPS = 0.08


def _flatten(steps: list[dict[str, Any]], mult: int = 1) -> list[tuple[float, dict[str, Any]]]:
    """(weighted duration, step) for every leaf, repeats expanded."""
    out: list[tuple[float, dict[str, Any]]] = []
    for s in steps:
        if s.get("kind") == "repeat":
            out.extend(_flatten(s.get("steps") or [], mult * int(s.get("iterations") or 1)))
            continue
        out.append((float(s.get("end_value") or s.get("duration_s") or 0) * mult, s))
    return out


def _target_of(step: dict[str, Any]) -> tuple[str, float, float] | None:
    """Normalise a step's target to (kind, low, high), whichever shape it is in."""
    t = step.get("target")
    if isinstance(t, dict) and t.get("type") == "hr":
        return "hr", float(t["low_bpm"]), float(t["high_bpm"])
    if isinstance(t, dict) and t.get("type") == "pace":
        return "pace", float(t["low_mps"]), float(t["high_mps"])

    tt = step.get("target_type")
    lo, hi = step.get("target_low"), step.get("target_high")
    if not tt or tt == "no.target" or lo is None or hi is None:
        return None
    if tt == "heart.rate.zone":
        return "hr", float(min(lo, hi)), float(max(lo, hi))
    if tt == "pace.zone":
        return "pace", float(min(lo, hi)), float(max(lo, hi))
    return None


def primary_target(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The target the session is really about, plus how much of it is spent there.

    The heaviest targeted leaf — so an interval session is judged on its work
    bouts, not on a warmup that happens to be longer than any single rep.
    """
    leaves = _flatten(steps)
    total = sum(w for w, _ in leaves) or 1.0

    best: tuple[float, tuple[str, float, float]] | None = None
    for weight, step in leaves:
        tgt = _target_of(step)
        if tgt is None:
            continue
        if best is None or weight > best[0]:
            best = (weight, tgt)

    if best is None:
        return None
    weight, (kind, low, high) = best
    return {
        "kind": kind,
        "low": low,
        "high": high,
        "work_seconds": weight,
        "work_fraction": min(1.0, weight / total),
    }


def representative_hr(hr_series: list[float | None], fraction: float) -> float | None:
    """Mean of the hardest `fraction` of the session.

    The activity does not record where each prescribed step began, so the work
    bouts cannot be sliced out directly. But if the prescription says a quarter
    of the session is hard, the hardest quarter of the samples is a fair stand-in
    — and for a steady run, where fraction is ~1, it degrades to the plain mean.
    """
    vals = sorted((float(v) for v in hr_series if v is not None), reverse=True)
    if not vals:
        return None
    take = max(1, int(round(len(vals) * max(0.02, min(1.0, fraction)))))
    top = vals[:take]
    return sum(top) / len(top)


def judge(actual: float, low: float, high: float, tolerance: float) -> Verdict:
    if actual > high + tolerance:
        return "too_hard"
    if actual < low - tolerance:
        return "too_easy"
    return "about_right"


def suggest_shift(actual: float, low: float, high: float, verdict: Verdict) -> int:
    """How far to move the band so the same effort would land inside it.

    Deliberately conservative — shifts to the edge, not to the middle, so one
    ordinary session does not swing the whole plan.
    """
    if verdict == "too_hard":
        return int(round(actual - high))
    if verdict == "too_easy":
        return int(round(actual - low))
    return 0


def review_session(
    activity: dict[str, Any],
    workout: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare one completed activity with its prescribed workout."""
    base = {
        "activity_id": activity.get("activity_id"),
        "activity_name": activity.get("name"),
        "date": (activity.get("start_local") or "")[:10],
        "workout_id": (workout or {}).get("workout_id"),
        "workout_name": (workout or {}).get("name"),
        "verdict": "unknown",
        "target": None,
        "actual": None,
        "suggested_shift": 0,
        "evidence": None,
    }

    if not workout:
        base["evidence"] = "No workout was scheduled for this date, so there is nothing to compare against."
        return base

    steps = [s for seg in (workout.get("segments") or []) for s in (seg.get("steps") or [])]
    target = primary_target(steps)
    if target is None:
        base["evidence"] = "The prescribed workout carries no pace or heart-rate target."
        return base

    base["target"] = target

    if target["kind"] == "hr":
        series = ((activity.get("series") or {}).get("hr")) or []
        actual = representative_hr(series, target["work_fraction"])
        if actual is None:
            actual = activity.get("avg_hr")
        if actual is None:
            base["evidence"] = "This activity has no heart-rate data."
            return base
        actual = float(actual)
        verdict = judge(actual, target["low"], target["high"], HR_TOLERANCE_BPM)
        pct = int(round(target["work_fraction"] * 100))
        # A steady run is targeted end to end, so "hardest 100%" is just the mean.
        measured = (
            f"the session averaged {actual:.0f} bpm"
            if target["work_fraction"] >= 0.95
            else f"the hardest {pct}% of the session averaged {actual:.0f} bpm"
        )
        base.update(
            verdict=verdict,
            actual=round(actual, 1),
            suggested_shift=suggest_shift(actual, target["low"], target["high"], verdict),
            evidence=(
                f"Prescribed {int(target['low'])}–{int(target['high'])} bpm; {measured}."
            ),
        )
        return base

    # Pace: average speed is all that can be compared fairly, since the series
    # pace is noisy and terrain-dependent.
    actual_mps = activity.get("avg_speed_mps")
    if actual_mps is None:
        base["evidence"] = "This activity has no speed data."
        return base
    actual_mps = float(actual_mps)
    verdict = judge(actual_mps, target["low"], target["high"], PACE_TOLERANCE_MPS)
    base.update(
        verdict=verdict,
        actual=round(actual_mps, 3),
        suggested_shift=0,  # pace shifts are expressed in s/km by the caller
        evidence=(
            f"Prescribed {target['low']:.2f}–{target['high']:.2f} m/s. "
            f"Session averaged {actual_mps:.2f} m/s."
        ),
    )
    return base

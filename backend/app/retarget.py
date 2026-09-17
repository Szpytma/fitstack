"""Shift the targets of workouts already sitting on the calendar.

Garmin's read shape is richer than the write shape FitStack can build, and
`update_workout` replaces the whole workout — so anything this module cannot
faithfully rebuild must be *skipped*, never rewritten. A silently mangled
workout is worse than one that was left alone.

Mirrors `frontend/src/lib/workoutSpec.ts`; keep the two in step.
"""

from __future__ import annotations

from typing import Any, Literal

Unit = Literal["bpm", "sec_per_km"]

WRITABLE_KINDS = {"warmup", "interval", "recovery", "cooldown", "repeat"}

MIN_BPM, MAX_BPM = 60, 220
# Below ~2:30/km is not a running pace; guards against a delta inverting a target.
MIN_SEC_PER_KM, MAX_SEC_PER_KM = 150.0, 900.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def spec_from_detail(detail: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Convert a workout's read shape back into a writable spec.

    Returns `(None, reasons)` when the workout uses anything the write path
    cannot express — a lap-button step, a distance-based step, a cadence or
    power target, or multiple sport segments.
    """
    blockers: list[str] = []
    segments = detail.get("segments") or []
    if len(segments) > 1:
        blockers.append("multiple sport segments")

    def convert(step: dict[str, Any]) -> dict[str, Any] | None:
        kind = step.get("kind")
        if kind == "repeat":
            inner = [c for c in (convert(s) for s in (step.get("steps") or [])) if c]
            return {"kind": "repeat", "iterations": step.get("iterations") or 1, "steps": inner}

        if kind not in WRITABLE_KINDS:
            blockers.append(f'step type "{kind}"')
            return None
        if step.get("end_condition") != "time":
            blockers.append(f'{step.get("end_condition") or "unknown"} step')
            return None

        out: dict[str, Any] = {"kind": kind, "duration_s": step.get("end_value") or 0}

        t = step.get("target_type")
        lo, hi = step.get("target_low"), step.get("target_high")
        if t and t != "no.target":
            if lo is None or hi is None:
                pass  # a target with no bounds carries nothing to preserve
            elif t == "heart.rate.zone":
                out["target"] = {
                    "type": "hr",
                    "low_bpm": int(round(min(lo, hi))),
                    "high_bpm": int(round(max(lo, hi))),
                }
            elif t == "pace.zone":
                out["target"] = {
                    "type": "pace",
                    "low_mps": float(min(lo, hi)),
                    "high_mps": float(max(lo, hi)),
                }
            else:
                blockers.append(f"{t.replace('.zone', '')} target")
                return None
        return out

    steps = [c for c in (convert(s) for s in (segments[0].get("steps") if segments else []) or []) if c]
    if not steps:
        blockers.append("no rebuildable steps")

    if blockers:
        # De-duplicate while keeping order, so a 10x repeat reports once.
        seen: dict[str, None] = {}
        for b in blockers:
            seen.setdefault(b, None)
        return None, list(seen)

    return (
        {
            "name": detail.get("name") or "Workout",
            "estimated_duration_s": detail.get("estimated_duration_s"),
            "steps": steps,
        },
        [],
    )


def shift_steps(steps: list[dict[str, Any]], delta: float, unit: Unit) -> list[dict[str, Any]]:
    """Apply a delta to every matching target. Positive is always *harder*."""
    out: list[dict[str, Any]] = []
    for s in steps:
        step = dict(s)
        if step.get("kind") == "repeat":
            step["steps"] = shift_steps(step.get("steps") or [], delta, unit)
            out.append(step)
            continue

        t = step.get("target")
        if t and unit == "bpm" and t.get("type") == "hr":
            step["target"] = {
                "type": "hr",
                "low_bpm": int(round(_clamp(t["low_bpm"] + delta, MIN_BPM, MAX_BPM))),
                "high_bpm": int(round(_clamp(t["high_bpm"] + delta, MIN_BPM, MAX_BPM))),
            }
        elif t and unit == "sec_per_km" and t.get("type") == "pace":
            # Harder means fewer seconds per km, so the delta subtracts.
            lo = _clamp(1000.0 / t["low_mps"] - delta, MIN_SEC_PER_KM, MAX_SEC_PER_KM)
            hi = _clamp(1000.0 / t["high_mps"] - delta, MIN_SEC_PER_KM, MAX_SEC_PER_KM)
            step["target"] = {
                "type": "pace",
                "low_mps": round(1000.0 / lo, 3),
                "high_mps": round(1000.0 / hi, 3),
            }
        out.append(step)
    return out


def has_matching_target(steps: list[dict[str, Any]], unit: Unit) -> bool:
    """Whether shifting would change anything, so no-op writes can be skipped."""
    want = "hr" if unit == "bpm" else "pace"
    for s in steps:
        if s.get("kind") == "repeat":
            if has_matching_target(s.get("steps") or [], unit):
                return True
            continue
        if (s.get("target") or {}).get("type") == want:
            return True
    return False

import type {
  PlanSession,
  PlanTargetMode,
  RunningWorkoutSpec,
  WorkoutStep,
} from "@/api/types";

/** Per-plan tweaks applied on top of what the planner produced.
 *
 *  Deltas, not absolutes: rebuilding the plan changes every number, but "10 bpm
 *  easier than whatever you calculated" stays meaningful.
 *
 *  Units follow the target mode — bpm in HR mode, seconds per km in pace mode.
 *  Positive is always *harder* (higher HR, faster pace) so one control reads the
 *  same way in both modes.
 */
export interface PlanAdjust {
  global: number;
  /** Keyed by session date; added on top of `global`. */
  perSession: Record<string, number>;
}

export const NO_ADJUST: PlanAdjust = { global: 0, perSession: {} };

export function deltaFor(adj: PlanAdjust, date: string): number {
  return adj.global + (adj.perSession[date] ?? 0);
}

export function hasAnyAdjust(adj: PlanAdjust): boolean {
  return adj.global !== 0 || Object.values(adj.perSession).some((v) => v !== 0);
}

const MIN_BPM = 60;
const MAX_BPM = 220;
/** Below this a pace is nonsense; guards against a delta inverting the target. */
const MIN_SEC_PER_KM = 150;
const MAX_SEC_PER_KM = 900;

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** m/s → seconds per km. */
function mpsToSecPerKm(mps: number): number {
  return 1000 / mps;
}

function secPerKmToMps(sec: number): number {
  return 1000 / sec;
}

function shiftStep(step: WorkoutStep, mode: PlanTargetMode, delta: number): WorkoutStep {
  if (step.kind === "repeat") {
    return {
      ...step,
      steps: (step.steps ?? []).map((s) => shiftStep(s, mode, delta)),
    };
  }
  const t = step.target;
  if (!t) return step;

  if (mode === "hr" && t.type === "hr") {
    return {
      ...step,
      target: {
        type: "hr",
        low_bpm: Math.round(clamp(t.low_bpm + delta, MIN_BPM, MAX_BPM)),
        high_bpm: Math.round(clamp(t.high_bpm + delta, MIN_BPM, MAX_BPM)),
      },
    };
  }
  if (mode === "pace" && t.type === "pace") {
    // Positive delta means harder, and harder is *fewer* seconds per km.
    const lo = clamp(mpsToSecPerKm(t.low_mps) - delta, MIN_SEC_PER_KM, MAX_SEC_PER_KM);
    const hi = clamp(mpsToSecPerKm(t.high_mps) - delta, MIN_SEC_PER_KM, MAX_SEC_PER_KM);
    return {
      ...step,
      target: {
        type: "pace",
        low_mps: Number(secPerKmToMps(lo).toFixed(3)),
        high_mps: Number(secPerKmToMps(hi).toFixed(3)),
      },
    };
  }
  return step;
}

export function shiftSpec(
  spec: RunningWorkoutSpec,
  mode: PlanTargetMode,
  delta: number,
): RunningWorkoutSpec {
  if (!delta) return spec;
  return { ...spec, steps: spec.steps.map((s) => shiftStep(s, mode, delta)) };
}

function fmtClock(totalSec: number): string {
  const t = Math.round(totalSec);
  const m = Math.floor(t / 60);
  const s = t % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** The band a session is actually run at: the longest targeted leaf, so an
 *  interval session is described by its work bouts and not by its warmup.
 *  Mirrors `hr_label_for_steps` in the planner. */
export function labelForSpec(
  spec: RunningWorkoutSpec | null | undefined,
  mode: PlanTargetMode,
): string | null {
  if (!spec) return null;

  // Flatten to targeted leaves with their total weight, then pick the heaviest.
  const leaves: { weight: number; step: WorkoutStep }[] = [];
  const walk = (steps: WorkoutStep[], mult: number) => {
    for (const s of steps) {
      if (s.kind === "repeat") {
        walk(s.steps ?? [], mult * (s.iterations ?? 1));
        continue;
      }
      if (!s.target) continue;
      leaves.push({ weight: (s.duration_s ?? 0) * mult, step: s });
    }
  };
  walk(spec.steps, 1);
  if (!leaves.length) return null;

  const t = leaves.reduce((a, b) => (b.weight > a.weight ? b : a)).step.target;
  if (!t) return null;
  if (t.type === "hr") return `${t.low_bpm}–${t.high_bpm} bpm`;
  if (mode === "pace" && t.type === "pace") {
    // Larger m/s is the faster pace, so it reads first.
    const fast = fmtClock(mpsToSecPerKm(Math.max(t.low_mps, t.high_mps)));
    const slow = fmtClock(mpsToSecPerKm(Math.min(t.low_mps, t.high_mps)));
    return `${fast}/km–${slow}/km`;
  }
  return null;
}

/** The session as it would be pushed, with adjustments folded in. */
export function adjustedSession(
  s: PlanSession,
  mode: PlanTargetMode,
  adj: PlanAdjust,
): { spec: RunningWorkoutSpec | null; label: string | null; delta: number } {
  const delta = deltaFor(adj, s.date);
  if (!s.spec) return { spec: null, label: null, delta };
  const spec = shiftSpec(s.spec, mode, delta);
  return { spec, label: labelForSpec(spec, mode), delta };
}

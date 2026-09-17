import type {
  RunningWorkoutSpec,
  WorkoutDetail,
  WorkoutDetailStep,
  WorkoutStep,
  WorkoutStepKind,
} from "@/api/types";

/**
 * Garmin's read shape is richer than the write shape FitStack can build.
 * Converting a workout back into an editable spec therefore has to be
 * conservative: `PUT /workouts/{id}` replaces the whole workout, so anything
 * this converter cannot represent would be silently destroyed on save.
 *
 * Rather than degrade the workout, unconvertible features are reported as
 * blockers and the caller refuses to edit.
 */
export interface SpecFromDetail {
  spec: RunningWorkoutSpec | null;
  blockers: string[];
}

const WRITABLE_KINDS: WorkoutStepKind[] = [
  "warmup",
  "interval",
  "recovery",
  "cooldown",
  "repeat",
];

function describeEnd(c: string | null | undefined): string {
  if (c === "lap.button") return "a lap-button step";
  if (c === "calories") return "a calorie-based step";
  return `an unsupported end condition (${c ?? "none"})`;
}

function convertStep(s: WorkoutDetailStep, blockers: Set<string>): WorkoutStep | null {
  const kind = (s.kind ?? "") as WorkoutStepKind;

  if (kind === "repeat") {
    const inner = (s.steps ?? [])
      .map((c) => convertStep(c, blockers))
      .filter((c): c is WorkoutStep => c !== null);
    return { kind: "repeat", iterations: s.iterations ?? 1, steps: inner };
  }

  if (!WRITABLE_KINDS.includes(kind)) {
    blockers.add(`it contains a step type FitStack cannot rebuild ("${s.kind ?? "?"}")`);
    return null;
  }

  // Time and distance both survive the round trip. What does not is anything
  // whose end the spec cannot state — "until I press lap", or a calorie count.
  if (s.end_condition !== "time" && s.end_condition !== "distance") {
    blockers.add(`it uses ${describeEnd(s.end_condition)}`);
    return null;
  }

  const step: WorkoutStep =
    s.end_condition === "distance"
      ? { kind, distance_m: s.end_value ?? 0 }
      : { kind, duration_s: s.end_value ?? 0 };

  const t = s.target_type;
  if (t && t !== "no.target") {
    const lo = s.target_low;
    const hi = s.target_high;
    if (lo == null || hi == null) {
      // A target with no bounds — nothing to preserve, drop it silently.
    } else if (t === "pace.zone") {
      step.target = {
        type: "pace",
        low_mps: Math.min(lo, hi),
        high_mps: Math.max(lo, hi),
      };
    } else if (t === "heart.rate.zone") {
      step.target = {
        type: "hr",
        low_bpm: Math.round(Math.min(lo, hi)),
        high_bpm: Math.round(Math.max(lo, hi)),
      };
    } else {
      blockers.add(`it has a ${t.replace(".zone", "")} target, which FitStack cannot rebuild`);
      return null;
    }
  }

  return step;
}

export function specFromDetail(detail: WorkoutDetail): SpecFromDetail {
  const blockers = new Set<string>();
  const segments = detail.segments ?? [];

  if (segments.length > 1) {
    blockers.add("it has multiple sport segments");
  }

  const steps = (segments[0]?.steps ?? [])
    .map((s) => convertStep(s, blockers))
    .filter((s): s is WorkoutStep => s !== null);

  if (!steps.length) blockers.add("it has no steps FitStack can rebuild");

  if (blockers.size) return { spec: null, blockers: [...blockers] };

  return {
    spec: {
      name: detail.name ?? "Workout",
      estimated_duration_s: detail.estimated_duration_s ?? null,
      steps,
    },
    blockers: [],
  };
}

/** Walk every leaf step, applying `fn`. Returns a new tree. */
export function mapLeaves(
  steps: WorkoutStep[],
  fn: (s: WorkoutStep, path: string) => WorkoutStep,
  prefix = "",
): WorkoutStep[] {
  return steps.map((s, i) => {
    const path = prefix ? `${prefix}.${i}` : String(i);
    if (s.kind === "repeat") {
      return { ...s, steps: mapLeaves(s.steps ?? [], fn, path) };
    }
    return fn(s, path);
  });
}

/** Total seconds a spec prescribes, repeats expanded.
 *
 *  Distance steps contribute nothing: how long 1 km takes is a fact about the
 *  athlete on the day, not about the workout, and Garmin estimates it itself.
 */
export function specDuration(steps: WorkoutStep[]): number {
  return steps.reduce((total, s) => {
    if (s.kind === "repeat") {
      return total + specDuration(s.steps ?? []) * (s.iterations ?? 1);
    }
    return total + (s.duration_s ?? 0);
  }, 0);
}

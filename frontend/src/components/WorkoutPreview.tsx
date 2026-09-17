import { useWorkoutDetail } from "@/api/hooks";
import { Pencil } from "lucide-react";
import type { WorkoutDetail, WorkoutDetailStep } from "@/api/types";

export function fmtClock(s: number): string {
  const total = Math.round(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return h
    ? `${h}:${mm}:${String(sec).padStart(2, "0")}`
    : `${mm}:${String(sec).padStart(2, "0")}`;
}

/** m/s → mm:ss per km. */
export function mpsToPace(mps: number): string {
  if (!mps || mps <= 0) return "—";
  return `${fmtClock(1000 / mps)}/km`;
}

/** How the step ends: time, distance, lap button, … */
export function fmtEnd(step: WorkoutDetailStep): string {
  const v = step.end_value;
  switch (step.end_condition) {
    case "time":
      return v != null ? fmtClock(v) : "time";
    case "distance":
      return v != null
        ? v >= 1000
          ? `${(v / 1000).toFixed(v % 1000 === 0 ? 0 : 2)} km`
          : `${Math.round(v)} m`
        : "distance";
    case "lap.button":
      return "lap button";
    case "calories":
      return v != null ? `${Math.round(v)} kcal` : "calories";
    case "iterations":
      return v != null ? `${v}×` : "reps";
    case null:
    case undefined:
      return "—";
    default:
      return v != null ? `${step.end_condition} ${v}` : step.end_condition;
  }
}

/**
 * Garmin returns target types the write path cannot build (cadence, power,
 * plain zone numbers) — render them all rather than showing a blank.
 */
export function fmtTarget(step: WorkoutDetailStep): string | null {
  const { target_type: t, target_low: lo, target_high: hi, zone } = step;
  if (!t || t === "no.target") {
    return zone != null ? `zone ${zone}` : null;
  }
  // Garmin does not guarantee targetValueOne < targetValueTwo — pace zones come
  // back with the faster (larger m/s) value first. Always sort before rendering.
  const lo2 = lo != null && hi != null ? Math.min(lo, hi) : null;
  const hi2 = lo != null && hi != null ? Math.max(lo, hi) : null;

  const range = (unit: string, digits = 0) =>
    lo2 != null && hi2 != null
      ? `${lo2.toFixed(digits)}–${hi2.toFixed(digits)} ${unit}`
      : zone != null
        ? `zone ${zone}`
        : t;

  switch (t) {
    case "pace.zone":
      // Stored as m/s: the larger value is the faster (lower) pace, so it leads.
      return hi2 != null && lo2 != null
        ? `${mpsToPace(hi2)}–${mpsToPace(lo2)}`
        : zone != null
          ? `pace zone ${zone}`
          : "pace";
    case "heart.rate.zone":
      return lo2 != null && hi2 != null
        ? `${Math.round(lo2)}–${Math.round(hi2)} bpm`
        : zone != null
          ? `HR zone ${zone}`
          : "heart rate";
    case "cadence":
      return range("spm");
    case "power.zone":
      return range("W");
    case "speed.zone":
      return range("m/s", 2);
    default:
      return range(t);
  }
}

const STEP_STYLE: Record<string, { bar: string; label: string }> = {
  warmup: { bar: "bg-sky-500/70", label: "text-sky-300" },
  interval: { bar: "bg-emerald-500/70", label: "text-emerald-300" },
  recovery: { bar: "bg-slate-600", label: "text-slate-400" },
  cooldown: { bar: "bg-indigo-500/70", label: "text-indigo-300" },
  rest: { bar: "bg-slate-600", label: "text-slate-400" },
};

export function stepStyle(kind: string | null) {
  return STEP_STYLE[kind ?? ""] ?? { bar: "bg-slate-700", label: "text-slate-300" };
}

export function StepList({
  steps,
  depth = 0,
}: {
  steps: WorkoutDetailStep[];
  depth?: number;
}) {
  return (
    <ol className="space-y-1">
      {steps.map((s, i) => {
        if (s.kind === "repeat") {
          return (
            <li key={i}>
              <div className="flex items-center gap-2 text-xs text-slate-300">
                <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-200 font-medium">
                  {s.iterations ?? "?"}×
                </span>
                <span className="text-slate-500">repeat</span>
              </div>
              <div className="mt-1 ml-3 pl-3 border-l border-dashed border-slate-700">
                <StepList steps={s.steps ?? []} depth={depth + 1} />
              </div>
            </li>
          );
        }
        const style = stepStyle(s.kind);
        const target = fmtTarget(s);
        return (
          <li key={i} className="flex items-center gap-2 text-xs">
            <span className={`w-1 h-4 rounded-full shrink-0 ${style.bar}`} />
            <span className={`w-14 sm:w-20 shrink-0 capitalize truncate ${style.label}`}>
              {s.kind ?? "step"}
            </span>
            <span className="text-slate-200 tabular-nums w-16 sm:w-24 shrink-0">{fmtEnd(s)}</span>
            <span className="text-slate-500 truncate">{target ?? ""}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Fetches and renders one workout's step structure. Used by both the
 *  Workouts list and the Coach schedule.
 *
 *  `onEdit` receives the loaded detail — the editor needs the full structure,
 *  and this component has already paid for it. */
export function WorkoutPreview({
  workoutId,
  onEdit,
}: {
  workoutId: number;
  onEdit?: (detail: WorkoutDetail) => void;
}) {
  const detail = useWorkoutDetail(workoutId);

  if (detail.isLoading) {
    return <div className="text-xs text-slate-500 py-2">Loading steps…</div>;
  }
  if (detail.isError) {
    return (
      <div className="text-xs text-red-400 py-2">
        Could not load steps: {(detail.error as Error).message}
      </div>
    );
  }

  const segments = detail.data?.segments ?? [];
  const steps = segments.flatMap((seg) => seg.steps ?? []);
  if (!steps.length) {
    return <div className="text-xs text-slate-500 py-2">No steps on this workout.</div>;
  }

  const dist = detail.data?.estimated_distance_m;
  const dur = detail.data?.estimated_duration_s;
  return (
    <div className="mt-3 rounded-lg bg-slate-950/60 border border-slate-800 p-3 space-y-2">
      <StepList steps={steps} />
      {(dist != null || dur != null || onEdit) && (
        <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-800 flex items-center gap-4">
          {dist != null && <span>Estimated distance {(dist / 1000).toFixed(2)} km</span>}
          {dur != null && <span>Estimated time {fmtClock(dur)}</span>}
          {onEdit && detail.data && (
            <button
              onClick={() => onEdit(detail.data as WorkoutDetail)}
              className="ml-auto inline-flex items-center gap-1 text-slate-400 hover:text-emerald-400"
            >
              <Pencil className="w-3 h-3" /> Edit
            </button>
          )}
        </div>
      )}
    </div>
  );
}

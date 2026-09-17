import { useMemo, useState } from "react";
import { AlertTriangle, Check, Save, X } from "lucide-react";
import type { RunningWorkoutSpec, WorkoutDetail, WorkoutStep } from "@/api/types";
import { useUpdateRunningWorkout } from "@/api/hooks";
import { mapLeaves, specDuration, specFromDetail } from "@/lib/workoutSpec";

interface Props {
  workoutId: number;
  detail: WorkoutDetail;
  onClose: () => void;
}

function fmtClock(s: number): string {
  const t = Math.round(s);
  const m = Math.floor(t / 60);
  return `${m}:${String(t % 60).padStart(2, "0")}`;
}

function mpsToPaceStr(mps: number): string {
  if (!mps || mps <= 0) return "0:00";
  return fmtClock(1000 / mps);
}

function paceStrToMps(v: string): number | null {
  if (!v.includes(":")) return null;
  const [m, s] = v.split(":").map(Number);
  if (isNaN(m) || isNaN(s)) return null;
  const sec = m * 60 + s;
  return sec > 0 ? 1000 / sec : null;
}

/** Flattened view of the leaves, so the form can address each one by path. */
function leaves(steps: WorkoutStep[], prefix = ""): { path: string; step: WorkoutStep }[] {
  return steps.flatMap((s, i) => {
    const path = prefix ? `${prefix}.${i}` : String(i);
    return s.kind === "repeat"
      ? leaves(s.steps ?? [], path)
      : [{ path, step: s }];
  });
}

export function WorkoutEditor({ workoutId, detail, onClose }: Props) {
  const converted = useMemo(() => specFromDetail(detail), [detail]);
  const [spec, setSpec] = useState<RunningWorkoutSpec | null>(converted.spec);
  const update = useUpdateRunningWorkout();

  if (converted.blockers.length || !spec) {
    return (
      <div className="mt-3 rounded-lg bg-amber-500/5 border border-amber-500/20 p-3 space-y-2">
        <div className="flex items-start gap-2 text-xs text-amber-200/90">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-400" />
          <div>
            <div className="font-medium">This workout can't be edited here safely.</div>
            <ul className="mt-1 space-y-0.5 text-amber-200/70">
              {converted.blockers.map((b, i) => (
                <li key={i}>— {b}</li>
              ))}
            </ul>
            <div className="mt-1.5 text-amber-200/60">
              Saving replaces the whole workout in Garmin, so anything FitStack can't
              rebuild would be lost. Edit it in Garmin Connect instead.
            </div>
          </div>
        </div>
        <button onClick={onClose} className="text-xs text-slate-400 hover:text-slate-200">
          Close
        </button>
      </div>
    );
  }

  const rows = leaves(spec.steps);
  const dirty = JSON.stringify(spec) !== JSON.stringify(converted.spec);

  const patchLeaf = (path: string, patch: Partial<WorkoutStep>) =>
    setSpec((prev) =>
      prev
        ? {
            ...prev,
            steps: mapLeaves(prev.steps, (s, p) => (p === path ? { ...s, ...patch } : s)),
          }
        : prev,
    );

  function save() {
    if (!spec) return;
    // Keep the estimate honest — the watch shows it.
    const withDuration: RunningWorkoutSpec = {
      ...spec,
      estimated_duration_s: Math.round(specDuration(spec.steps)),
    };
    update.mutate({ id: workoutId, spec: withDuration });
  }

  return (
    <div className="mt-3 rounded-lg bg-slate-950/60 border border-slate-800 p-3 space-y-3">
      <div className="flex items-center gap-2">
        <input
          value={spec.name}
          onChange={(e) => setSpec({ ...spec, name: e.target.value })}
          className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-100"
          aria-label="Workout name"
        />
        <span className="text-[11px] text-slate-500 tabular-nums shrink-0">
          {fmtClock(specDuration(spec.steps))} total
        </span>
      </div>

      <ol className="space-y-1.5">
        {rows.map(({ path, step }) => {
          const t = step.target;
          return (
            <li key={path} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="w-16 shrink-0 capitalize text-slate-400">{step.kind}</span>

              <label className="flex items-center gap-1">
                <span className="text-slate-600">sec</span>
                <input
                  type="number"
                  min={5}
                  max={14400}
                  value={Math.round(step.duration_s ?? 0)}
                  onChange={(e) => patchLeaf(path, { duration_s: Number(e.target.value) })}
                  className="w-20 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-slate-100 tabular-nums"
                  aria-label={`${step.kind} duration in seconds`}
                />
              </label>

              {t?.type === "hr" && (
                <span className="flex items-center gap-1">
                  <input
                    type="number"
                    min={60}
                    max={220}
                    value={t.low_bpm}
                    onChange={(e) =>
                      patchLeaf(path, { target: { ...t, low_bpm: Number(e.target.value) } })
                    }
                    className="w-16 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-slate-100 tabular-nums"
                    aria-label="Target HR low"
                  />
                  <span className="text-slate-600">–</span>
                  <input
                    type="number"
                    min={60}
                    max={220}
                    value={t.high_bpm}
                    onChange={(e) =>
                      patchLeaf(path, { target: { ...t, high_bpm: Number(e.target.value) } })
                    }
                    className="w-16 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-slate-100 tabular-nums"
                    aria-label="Target HR high"
                  />
                  <span className="text-slate-600">bpm</span>
                </span>
              )}

              {t?.type === "pace" && (
                <span className="flex items-center gap-1">
                  {/* Larger m/s is the faster pace, so it reads first. */}
                  <input
                    defaultValue={mpsToPaceStr(t.high_mps)}
                    onBlur={(e) => {
                      const mps = paceStrToMps(e.target.value);
                      if (mps) patchLeaf(path, { target: { ...t, high_mps: mps } });
                    }}
                    className="w-16 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-slate-100 tabular-nums"
                    aria-label="Target pace fast"
                  />
                  <span className="text-slate-600">–</span>
                  <input
                    defaultValue={mpsToPaceStr(t.low_mps)}
                    onBlur={(e) => {
                      const mps = paceStrToMps(e.target.value);
                      if (mps) patchLeaf(path, { target: { ...t, low_mps: mps } });
                    }}
                    className="w-16 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-slate-100 tabular-nums"
                    aria-label="Target pace slow"
                  />
                  <span className="text-slate-600">/km</span>
                </span>
              )}

              {!t && <span className="text-slate-600">no target</span>}
            </li>
          );
        })}
      </ol>

      <div className="flex items-center gap-2 pt-1 border-t border-slate-800">
        <button
          onClick={save}
          disabled={!dirty || update.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs disabled:opacity-40"
        >
          <Save className="w-3.5 h-3.5" />
          {update.isPending ? "Saving…" : "Save to Garmin"}
        </button>
        <button
          onClick={onClose}
          className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-400 hover:text-slate-200"
        >
          <X className="w-3.5 h-3.5" /> Cancel
        </button>
        {update.isSuccess && !dirty && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
            <Check className="w-3.5 h-3.5" /> Saved — scheduled dates kept.
          </span>
        )}
        {update.isError && (
          <span className="text-xs text-red-400">
            {(update.error as Error).message}
          </span>
        )}
        {dirty && !update.isPending && (
          <span className="text-[11px] text-slate-500 ml-auto">
            Replaces the workout in Garmin; every scheduled date using it changes too.
          </span>
        )}
      </div>
    </div>
  );
}

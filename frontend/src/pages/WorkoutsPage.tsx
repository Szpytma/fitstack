import { useState } from "react";
import {
  useCreateRunningWorkout,
  useDeleteWorkout,
  useDevices,
  usePushWorkoutToDevice,
  useScheduleWorkout,
  useWorkoutTemplates,
} from "@/api/hooks";
import type { RunningWorkoutSpec, WorkoutDetail, WorkoutSummary } from "@/api/types";
import { WorkoutPreview } from "@/components/WorkoutPreview";
import { WorkoutEditor } from "@/components/WorkoutEditor";
import {
  CalendarPlus,
  ChevronDown,
  ChevronRight,
  Dumbbell,
  Plus,
  Send,
  Trash2,
} from "lucide-react";

function fmtDuration(s: number | null): string {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function WorkoutsPage() {
  const workouts = useWorkoutTemplates(50);
  const devices = useDevices();

  return (
    <div className="max-w-6xl mx-auto p-4 sm:p-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div>
        <header className="mb-4 flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold text-slate-50">Workout templates</h1>
          <span className="text-xs text-slate-500">{workouts.data?.length ?? 0} on account</span>
        </header>
        <div className="rounded-xl bg-slate-900 border border-slate-800 divide-y divide-slate-800 max-h-[70vh] overflow-y-auto">
          {workouts.isLoading ? (
            <div className="p-4 text-slate-500 text-sm">Loading…</div>
          ) : !workouts.data?.length ? (
            <div className="p-4 text-slate-500 text-sm">No workouts yet.</div>
          ) : (
            workouts.data.map((w) => (
              <WorkoutRow key={w.workout_id} w={w} devices={devices.data ?? []} />
            ))
          )}
        </div>
      </div>

      <div>
        <header className="mb-4">
          <h1 className="text-2xl font-semibold text-slate-50">Create running workout</h1>
          <p className="text-slate-400 text-sm">
            Warmup + repeated intervals + cooldown. Uploads to your Garmin account.
          </p>
        </header>
        <WorkoutBuilder />
      </div>
    </div>
  );
}

function WorkoutRow({ w, devices }: { w: WorkoutSummary; devices: { device_id: number | null; name: string | null }[] }) {
  const del = useDeleteWorkout();
  const sched = useScheduleWorkout();
  const push = usePushWorkoutToDevice();
  const [scheduleDate, setScheduleDate] = useState("");
  const [showSched, setShowSched] = useState(false);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<WorkoutDetail | null>(null);

  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between">
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          title={open ? "Hide steps" : "Show steps"}
          className="min-w-0 flex items-center gap-2 text-left group"
        >
          {open ? (
            <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 shrink-0" />
          )}
          <div className="min-w-0">
            <div className="text-slate-100 font-medium truncate flex items-center gap-2 group-hover:text-white">
              <Dumbbell className="w-4 h-4 text-slate-500" />
              {w.name ?? "Workout"}
            </div>
            <div className="text-slate-500 text-xs mt-0.5">
              {w.sport ?? "—"} · {fmtDuration(w.estimated_duration_s)}
            </div>
          </div>
        </button>
        <div className="flex items-center gap-1 shrink-0">
          <button
            title="Schedule"
            onClick={() => setShowSched((v) => !v)}
            className="p-2 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200"
          >
            <CalendarPlus className="w-4 h-4" />
          </button>
          <button
            title="Push to device"
            onClick={() => push.mutate({ id: w.workout_id, deviceId: devices[0]?.device_id ?? undefined })}
            disabled={push.isPending}
            className="p-2 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 disabled:opacity-40"
          >
            <Send className="w-4 h-4" />
          </button>
          <button
            title="Delete"
            onClick={() => {
              if (confirm(`Delete "${w.name}"? This cannot be undone.`)) del.mutate(w.workout_id);
            }}
            disabled={del.isPending}
            className="p-2 rounded hover:bg-slate-800 text-slate-400 hover:text-red-400 disabled:opacity-40"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
      {open && !editing && (
        <WorkoutPreview workoutId={w.workout_id} onEdit={(d) => setEditing(d)} />
      )}
      {editing && (
        <WorkoutEditor
          workoutId={w.workout_id}
          detail={editing}
          onClose={() => setEditing(null)}
        />
      )}
      {showSched && (
        <div className="mt-2 flex gap-2 items-center text-xs">
          <input
            type="date"
            value={scheduleDate}
            onChange={(e) => setScheduleDate(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          />
          <button
            disabled={!scheduleDate || sched.isPending}
            onClick={() => {
              sched.mutate({ id: w.workout_id, date: scheduleDate }, { onSuccess: () => setShowSched(false) });
            }}
            className="px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-40"
          >
            {sched.isPending ? "…" : "Schedule"}
          </button>
        </div>
      )}
      {(del.error || sched.error || push.error) && (
        <div className="mt-2 text-xs text-red-400">
          {String((del.error || sched.error || push.error) as Error)}
        </div>
      )}
      {push.isSuccess && !push.isPending && (
        <div className="mt-2 text-xs text-emerald-400">Pushed. Sync your watch to receive.</div>
      )}
    </div>
  );
}

function paceToMps(minPerKm: string): number | null {
  if (!minPerKm.includes(":")) return null;
  const [m, s] = minPerKm.split(":").map(Number);
  if (isNaN(m) || isNaN(s)) return null;
  const secsPerKm = m * 60 + s;
  return 1000 / secsPerKm;
}

type TargetMode = "pace" | "hr";

function WorkoutBuilder() {
  const create = useCreateRunningWorkout();
  const [name, setName] = useState("My Tempo Run");
  const [warmupMin, setWarmupMin] = useState(10);
  const [reps, setReps] = useState(6);
  const [intervalSec, setIntervalSec] = useState(90);
  const [recoverySec, setRecoverySec] = useState(90);
  const [cooldownMin, setCooldownMin] = useState(10);
  const [mode, setMode] = useState<TargetMode>("pace");
  const [paceFast, setPaceFast] = useState("4:30");
  const [paceSlow, setPaceSlow] = useState("4:45");
  const [hrLow, setHrLow] = useState(130);
  const [hrHigh, setHrHigh] = useState(140);

  function buildTarget() {
    if (mode === "hr") {
      if (!hrLow || !hrHigh) return null;
      return {
        type: "hr" as const,
        low_bpm: Math.min(hrLow, hrHigh),
        high_bpm: Math.max(hrLow, hrHigh),
      };
    }
    const fast = paceToMps(paceFast);
    const slow = paceToMps(paceSlow);
    return fast && slow
      ? { type: "pace" as const, low_mps: Math.min(fast, slow), high_mps: Math.max(fast, slow) }
      : null;
  }

  function submit() {
    const target = buildTarget();

    const spec: RunningWorkoutSpec = {
      name,
      estimated_duration_s:
        warmupMin * 60 + reps * (intervalSec + recoverySec) + cooldownMin * 60,
      steps: [
        { kind: "warmup", duration_s: warmupMin * 60 },
        {
          kind: "repeat",
          iterations: reps,
          steps: [
            { kind: "interval", duration_s: intervalSec, target },
            { kind: "recovery", duration_s: recoverySec },
          ],
        },
        { kind: "cooldown", duration_s: cooldownMin * 60 },
      ],
    };
    create.mutate(spec);
  }

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 space-y-4">
      <Field label="Workout name">
        <input value={name} onChange={(e) => setName(e.target.value)} className="input" />
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Warmup (min)">
          <input type="number" min={0} max={60} value={warmupMin} onChange={(e) => setWarmupMin(Number(e.target.value))} className="input" />
        </Field>
        <Field label="Cooldown (min)">
          <input type="number" min={0} max={60} value={cooldownMin} onChange={(e) => setCooldownMin(Number(e.target.value))} className="input" />
        </Field>
      </div>

      <div className="border-t border-slate-800 pt-4">
        <div className="text-slate-300 text-sm font-medium mb-2">Interval set</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <Field label="Repeat"><input type="number" min={1} max={30} value={reps} onChange={(e) => setReps(Number(e.target.value))} className="input" /></Field>
          <Field label="Interval (sec)"><input type="number" min={10} max={1800} value={intervalSec} onChange={(e) => setIntervalSec(Number(e.target.value))} className="input" /></Field>
          <Field label="Recovery (sec)"><input type="number" min={10} max={1800} value={recoverySec} onChange={(e) => setRecoverySec(Number(e.target.value))} className="input" /></Field>
        </div>
        <div className="mt-3">
          <div className="text-xs text-slate-400 mb-1">Target the interval by</div>
          <div className="inline-flex rounded border border-slate-700 overflow-hidden text-xs">
            {(["pace", "hr"] as TargetMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                aria-pressed={mode === m}
                className={`px-3 py-1.5 ${
                  mode === m
                    ? "bg-emerald-600 text-white"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                }`}
              >
                {m === "pace" ? "Pace" : "Heart rate"}
              </button>
            ))}
          </div>
        </div>

        {mode === "pace" ? (
          <div className="grid grid-cols-2 gap-3 mt-3">
            <Field label="Target pace fast (mm:ss/km)"><input value={paceFast} onChange={(e) => setPaceFast(e.target.value)} className="input" placeholder="4:30" /></Field>
            <Field label="Target pace slow"><input value={paceSlow} onChange={(e) => setPaceSlow(e.target.value)} className="input" placeholder="4:45" /></Field>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 mt-3">
              <Field label="Target HR low (bpm)"><input type="number" min={60} max={220} value={hrLow} onChange={(e) => setHrLow(Number(e.target.value))} className="input" /></Field>
              <Field label="Target HR high (bpm)"><input type="number" min={60} max={220} value={hrHigh} onChange={(e) => setHrHigh(Number(e.target.value))} className="input" /></Field>
            </div>
            <p className="text-[11px] text-slate-500 mt-2">
              For a steady run at one heart rate, set Repeat to 1 and make the interval
              the whole run — e.g. 1 × 2400s at 130–140 bpm.
            </p>
          </>
        )}
      </div>

      <button
        disabled={create.isPending}
        onClick={submit}
        className="w-full py-2 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium disabled:opacity-40 flex items-center justify-center gap-2"
      >
        <Plus className="w-4 h-4" />
        {create.isPending ? "Uploading…" : "Create & upload to Garmin"}
      </button>

      {create.isSuccess && (
        <div className="text-emerald-400 text-sm">
          Uploaded (workout id {create.data?.workout_id}). Refresh templates list.
        </div>
      )}
      {create.isError && (
        <div className="text-red-400 text-sm">{String(create.error as Error)}</div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-xs text-slate-400 mb-1">{label}</div>
      {children}
    </label>
  );
}

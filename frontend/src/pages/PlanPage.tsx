import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Copy,
  MonitorSmartphone,
  Sparkles,
  Terminal,
  Upload,
  Wand2,
  Wrench,
  Zap,
} from "lucide-react";
import {
  useApplyPlan,
  usePlanPreview,
  usePlanStatus,
  useStartRollingPlan,
} from "@/api/hooks";
import type {
  PlanRequest,
  PlanTargetMode,
  RacePlan,
  RunningWorkoutSpec,
} from "@/api/types";
import { PlanTable } from "@/components/PlanTable";
import { RollingPlanCard, StartRollingButton } from "@/components/RollingPlanCard";
import { adjustedSession, hasAnyAdjust, NO_ADJUST, type PlanAdjust } from "@/lib/planAdjust";

const DESKTOP_CONFIG = `{
  "mcpServers": {
    "fitstack": {
      "command": "C:/Users/szpyt/source/repos/fitstack/backend/.venv/Scripts/python.exe",
      "args": ["-m", "app.mcp_server"],
      "cwd": "C:/Users/szpyt/source/repos/fitstack/backend"
    }
  }
}`;

const TOOLS: { name: string; desc: string; write?: boolean }[] = [
  { name: "get_daily_summary", desc: "One day of steps / calories / HR" },
  { name: "get_daily_summaries", desc: "N days of daily stats" },
  { name: "get_recent_activities", desc: "List of recent runs / rides" },
  { name: "get_activity_detail", desc: "Splits, HR zones, GPS, weather for one activity" },
  { name: "get_sleep", desc: "One night of sleep" },
  { name: "get_sleep_history", desc: "N nights of sleep" },
  { name: "get_upcoming_workouts", desc: "Scheduled Coach workouts" },
  { name: "get_workout_detail", desc: "Steps inside one workout template" },
  { name: "list_workout_templates", desc: "All saved templates" },
  { name: "list_devices", desc: "Your registered Garmin devices" },
  { name: "generate_race_plan", desc: "Whole periodised block, computed locally" },
  { name: "start_training_plan", desc: "Begin a rolling plan, return week one" },
  { name: "get_training_week", desc: "Next week, rebuilt against current fitness" },
  { name: "get_training_plan_status", desc: "Where you are in the block" },
  { name: "end_training_plan", desc: "Stop the rolling plan" },
  { name: "create_running_workout", desc: "Create a new template", write: true },
  { name: "schedule_workout", desc: "Put a template on a date", write: true },
  { name: "unschedule_workout", desc: "Remove a scheduled instance", write: true },
  { name: "delete_workout", desc: "Delete a template", write: true },
  { name: "push_workout_to_device", desc: "Send template to watch", write: true },
];

// -------------------- plan prompt builder --------------------

const RACES = [
  { key: "5k", label: "5K", phrase: "5K", km: 5, goal: "22:00" },
  { key: "10k", label: "10K", phrase: "10K", km: 10, goal: "48:00" },
  {
    key: "half",
    label: "Half · 21.1K",
    phrase: "half marathon (21.1 km)",
    km: 21.1,
    goal: "1:45:00",
  },
  {
    key: "full",
    label: "Marathon · 42.2K",
    phrase: "marathon (42.2 km)",
    km: 42.2,
    goal: "3:45:00",
  },
  { key: "custom", label: "Custom", phrase: "", km: 0, goal: "" },
] as const;

type RaceKey = (typeof RACES)[number]["key"];

const DAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

function todayISO(): string {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

function defaultRaceDate(): string {
  const d = new Date();
  d.setDate(d.getDate() + 12 * 7);
  return d.toISOString().slice(0, 10);
}

/** Whole weeks between today and the race, floor 1. */
function weeksUntil(raceDate: string): number | null {
  if (!raceDate) return null;
  const race = new Date(`${raceDate}T00:00:00`);
  if (isNaN(race.getTime())) return null;
  const now = new Date(`${todayISO()}T00:00:00`);
  const days = Math.round((race.getTime() - now.getTime()) / 86_400_000);
  if (days < 0) return null;
  return Math.max(1, Math.floor(days / 7));
}

interface PlanForm {
  race: RaceKey;
  customKm: string;
  raceDate: string;
  runsPerWeek: number;
  weeklyKm: string;
  goalTime: string;
  longRunDay: string;
  forSelf: boolean;
  athlete: string;
  athleteNotes: string;
  writeToGarmin: boolean;
  targetMode: PlanTargetMode;
  mode: "race" | "base";
  weeks: number;
  weeklyMinutes: string;
}

function buildPrompt(f: PlanForm): string {
  const race = RACES.find((r) => r.key === f.race)!;
  const km = f.race === "custom" ? Number(f.customKm) || 0 : race.km;
  const distance =
    f.race === "custom" ? (km ? `${km} km race` : "race") : race.phrase;
  const weeks = weeksUntil(f.raceDate);
  const span = weeks ? `a ${weeks}-week` : "a";

  // No name given for someone else's plan → just drop the recipient.
  const recipient = f.forSelf
    ? "me "
    : f.athlete.trim()
      ? `${f.athlete.trim()} `
      : "";

  const L: string[] = [];

  L.push(
    `Build ${recipient}${span} training plan for a ${distance}${
      f.raceDate ? ` on ${f.raceDate}` : ""
    }.`,
  );
  L.push("");

  L.push(f.forSelf ? "About me:" : "About the athlete:");
  if (!f.forSelf && f.athlete.trim()) L.push(`- Name: ${f.athlete.trim()}`);
  if (f.weeklyKm.trim())
    L.push(`- Current weekly volume: ${f.weeklyKm.trim()} km`);
  L.push(`- Available to run ${f.runsPerWeek} days/week`);
  L.push(`- Long run day: ${f.longRunDay}`);
  if (f.goalTime.trim()) L.push(`- Goal time: ${f.goalTime.trim()}`);
  if (!f.forSelf && f.athleteNotes.trim())
    L.push(`- Notes: ${f.athleteNotes.trim()}`);
  L.push("");

  if (f.forSelf) {
    L.push(
      "Before planning anything, read my actual training history with the FitStack MCP tools:",
    );
    L.push(
      "- get_recent_activities(limit=50) — recent runs: distance, pace, duration",
    );
    L.push(
      "- get_activity_detail(...) on 3-5 representative runs — splits, HR zones, cadence",
    );
    L.push(
      "- get_daily_summaries(days=90) — volume trend and resting HR direction",
    );
    L.push("- get_sleep_history(days=30) — how much recovery I actually get");
    L.push(
      "- get_upcoming_workouts() and list_workout_templates() — what is already on the calendar",
    );
    L.push("");
    L.push(
      "Base every pace target on what those runs show, not on a generic formula — and tell me which runs you derived them from.",
    );
    L.push("");
  }

  L.push("Then produce:");
  L.push(
    "1. A week-by-week table: week number, dates, total volume, and each session (type, distance or duration, target pace or HR).",
  );
  L.push(
    `2. Clear periodisation — base / build / peak / taper — with at least a 2-week taper into ${
      f.raceDate || "race day"
    }.`,
  );
  L.push(
    "3. Key sessions called out: long run, quality/threshold session, and easy days that are genuinely easy.",
  );
  L.push(
    "4. A flag on any week where volume jumps more than ~10% over the previous week.",
  );
  if (f.goalTime.trim())
    L.push(
      `5. An honest verdict on whether ${f.goalTime.trim()} is realistic from the current starting point — say so if it is not.`,
    );
  L.push("");

  if (f.forSelf && f.writeToGarmin) {
    L.push("Then put it into Garmin:");
    L.push(
      "- create_running_workout for each distinct session type (not one per calendar day)",
    );
    L.push("- schedule_workout to place them on the right dates");
    L.push("- Show me the full list and wait for my confirmation before any write call.");
    L.push("");
    L.push("Constraints for the write step:");
    L.push(
      "- Workout steps are time-based (seconds) — convert distance sessions using the goal pace.",
    );
    L.push("- Targets support pace (m/s range) and heart rate (bpm range) only.");
    L.push("- Keep each workout name under 100 characters.");
  }

  return L.join("\n").trim();
}

function PlanBuilder() {
  const [f, setF] = useState<PlanForm>({
    race: "half",
    customKm: "",
    raceDate: defaultRaceDate(),
    runsPerWeek: 4,
    weeklyKm: "30",
    goalTime: "",
    longRunDay: "Sunday",
    forSelf: true,
    athlete: "",
    athleteNotes: "",
    writeToGarmin: true,
    targetMode: "pace",
    mode: "race",
    weeks: 12,
    weeklyMinutes: "180",
  });
  const [copied, setCopied] = useState(false);
  const [adjust, setAdjust] = useState<PlanAdjust>(NO_ADJUST);

  const set = <K extends keyof PlanForm>(k: K, v: PlanForm[K]) =>
    setF((prev) => ({ ...prev, [k]: v }));

  const prompt = useMemo(() => buildPrompt(f), [f]);
  const weeks = weeksUntil(f.raceDate);

  const preview = usePlanPreview();
  const apply = useApplyPlan();
  const startRolling_ = useStartRollingPlan();
  const rollingStatus = usePlanStatus();
  const plan: RacePlan | undefined = preview.data;

  const raceKm =
    f.race === "custom"
      ? Number(f.customKm) || 0
      : RACES.find((r) => r.key === f.race)!.km;

  function planRequest(): PlanRequest {
    if (f.mode === "base") {
      return {
        mode: "base",
        weeks: f.weeks,
        weekly_minutes: f.weeklyMinutes.trim() ? Number(f.weeklyMinutes) : null,
        runs_per_week: f.runsPerWeek,
        long_run_day: f.longRunDay,
        race_name: "Aerobic base",
        use_history: f.forSelf,
      };
    }
    return {
      mode: "race",
      race_km: raceKm,
      race_date: f.raceDate,
      runs_per_week: f.runsPerWeek,
      long_run_day: f.longRunDay,
      weekly_km: f.weeklyKm.trim() ? Number(f.weeklyKm) : null,
      goal_time: f.goalTime.trim() || null,
      race_name: f.race === "custom" ? null : f.race.toUpperCase(),
      use_history: f.forSelf,
      target_mode: f.targetMode,
    };
  }

  function generate() {
    apply.reset();
    // A fresh plan recomputes every target; carrying old deltas over would
    // silently double-apply them.
    setAdjust(NO_ADJUST);
    preview.mutate(planRequest());
  }

  /** Same inputs, but only the current week comes back and the block's anchor is
   *  pinned — later weeks replay from it rather than restarting the periodisation. */
  function startRolling() {
    // Starting writes nothing to Garmin — only a local anchor — so the only
    // thing worth confirming is discarding a plan already in progress.
    if (
      rollingStatus.data &&
      !confirm(
        `Replace the ${rollingStatus.data.race_name ?? "current"} plan already running?` +
          "\n\nWorkouts already scheduled in Garmin are left alone.",
      )
    )
      return;
    preview.reset();
    apply.reset();
    setAdjust(NO_ADJUST);
    startRolling_.mutate(planRequest());
  }

  function pushToGarmin() {
    if (!plan) return;
    // Push what is on screen, adjustments included — never the raw plan.
    const sessions = plan.weeks
      .flatMap((w) => w.sessions)
      .filter((s) => s.spec?.steps?.length)
      .map((s) => ({
        date: s.date,
        spec: adjustedSession(s, plan.target_mode, adjust).spec as RunningWorkoutSpec,
      }));
    const distinct = new Set(sessions.map((s) => JSON.stringify(s.spec))).size;
    const tweak = hasAnyAdjust(adjust)
      ? `\n\nYour adjustments are included${
          adjust.global !== 0
            ? ` (all sessions ${adjust.global > 0 ? "+" : ""}${adjust.global} ${
                plan.target_mode === "hr" ? "bpm" : "s/km"
              })`
            : ""
        }.`
      : "";
    const ok = confirm(
      `Create ${distinct} workout templates in Garmin and schedule ` +
        `${sessions.length} sessions between ${sessions[0]?.date} and ` +
        `${sessions[sessions.length - 1]?.date}?${tweak}\n\nThis writes to your Garmin account.`,
    );
    if (ok) apply.mutate(sessions);
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
      <div>
        <h2 className="text-slate-100 font-medium flex items-center gap-2">
          <Wand2 className="w-4 h-4 text-emerald-400" /> Race plan prompt
        </h2>
        <p className="text-slate-400 text-sm mt-1">
          Fill this in, copy the prompt, paste it into Claude Code or Claude
          Desktop. Claude reads your Garmin data through the MCP tools below and
          builds the plan.
        </p>
      </div>

      <div>
        <div className="text-xs text-slate-400 mb-1.5">What are you training for</div>
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["race", "A race", "Periodised block: threshold, intervals, taper"],
              ["base", "Aerobic base", "Every run in zone 2, progressed by time"],
            ] as const
          ).map(([k, label, hint]) => (
            <button
              key={k}
              onClick={() => set("mode", k)}
              title={hint}
              className={`px-3 py-1.5 rounded-lg text-sm border ${
                f.mode === k
                  ? "bg-emerald-600 border-emerald-500 text-white"
                  : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {f.mode === "base" && (
          <p className="text-xs text-slate-500 mt-2">
            No race, no taper. Every run capped in zone 2, read from your Garmin
            zones, and the week grows in minutes rather than kilometres — at a fixed
            heart rate, distance is the outcome, not the target. Progress shows up as
            pace rising at the same heart rate.
          </p>
        )}
      </div>

      {f.mode === "base" && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Field label="Block length (weeks)">
            <input
              type="number"
              min={4}
              max={24}
              value={f.weeks}
              onChange={(e) => set("weeks", Number(e.target.value) || 12)}
              className="input"
            />
          </Field>
          <Field label="Current weekly minutes">
            <input
              type="number"
              min={0}
              value={f.weeklyMinutes}
              onChange={(e) => set("weeklyMinutes", e.target.value)}
              className="input"
            />
          </Field>
          <Field label="Runs per week">
            <input
              type="number"
              min={2}
              max={7}
              value={f.runsPerWeek}
              onChange={(e) => set("runsPerWeek", Number(e.target.value) || 4)}
              className="input"
            />
          </Field>
        </div>
      )}

      <div className={f.mode === "base" ? "hidden" : undefined}>
        <div className="text-xs text-slate-400 mb-1.5">Distance</div>
        <div className="flex flex-wrap gap-2">
          {RACES.map((r) => (
            <button
              key={r.key}
              onClick={() => set("race", r.key)}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                f.race === r.key
                  ? "bg-emerald-600 border-emerald-500 text-white"
                  : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-slate-100"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {f.race === "custom" && (
        <Field label="Custom distance (km)">
          <input
            type="number"
            min={1}
            step="0.1"
            value={f.customKm}
            onChange={(e) => set("customKm", e.target.value)}
            className="input"
            placeholder="e.g. 15"
          />
        </Field>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field
          label={`Race date${weeks ? ` · ${weeks} weeks away` : ""}`}
        >
          <input
            type="date"
            min={todayISO()}
            value={f.raceDate}
            onChange={(e) => set("raceDate", e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Goal time (optional)">
          <input
            value={f.goalTime}
            onChange={(e) => set("goalTime", e.target.value)}
            className="input"
            placeholder={RACES.find((r) => r.key === f.race)?.goal || "1:45:00"}
          />
        </Field>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Field label="Runs per week">
          <input
            type="number"
            min={2}
            max={7}
            value={f.runsPerWeek}
            onChange={(e) => set("runsPerWeek", Number(e.target.value))}
            className="input"
          />
        </Field>
        <Field label="Current weekly km">
          <input
            type="number"
            min={0}
            value={f.weeklyKm}
            onChange={(e) => set("weeklyKm", e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Long run day">
          <select
            value={f.longRunDay}
            onChange={(e) => set("longRunDay", e.target.value)}
            className="input"
          >
            {DAYS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="border-t border-slate-800 pt-4 space-y-3">
        <div>
          <div className="text-xs text-slate-400 mb-1">Target sessions by</div>
          <div className="inline-flex rounded border border-slate-700 overflow-hidden text-xs">
            {(["pace", "hr"] as PlanTargetMode[]).map((m) => (
              <button
                key={m}
                onClick={() => set("targetMode", m)}
                aria-pressed={f.targetMode === m}
                className={`px-3 py-1.5 ${
                  f.targetMode === m
                    ? "bg-emerald-600 text-white"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                }`}
              >
                {m === "pace" ? "Pace" : "Heart rate"}
              </button>
            ))}
          </div>
          {f.targetMode === "hr" && (
            <p className="text-[11px] text-slate-500 mt-1.5">
              Distances and durations still come from pace — only what the watch chases
              changes. Bands come from your configured Garmin zones.
            </p>
          )}
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={f.forSelf}
            onChange={(e) => set("forSelf", e.target.checked)}
            className="accent-emerald-500"
          />
          Plan for me — use my Garmin history
        </label>

        {!f.forSelf ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Who is it for">
              <input
                value={f.athlete}
                onChange={(e) => set("athlete", e.target.value)}
                className="input"
                placeholder="e.g. Anna"
              />
            </Field>
            <Field label="Their background (optional)">
              <input
                value={f.athleteNotes}
                onChange={(e) => set("athleteNotes", e.target.value)}
                className="input"
                placeholder="e.g. new to running, past knee injury"
              />
            </Field>
          </div>
        ) : (
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={f.writeToGarmin}
              onChange={(e) => set("writeToGarmin", e.target.checked)}
              className="accent-emerald-500"
            />
            Also create and schedule the sessions in Garmin
          </label>
        )}
        {!f.forSelf && (
          <p className="text-xs text-slate-500">
            Someone else&apos;s plan is built from what you type here — your
            Garmin data and the write tools stay out of it.
          </p>
        )}
      </div>

      <div className="border-t border-slate-800 pt-4 space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={generate}
            disabled={preview.isPending || raceKm <= 0 || (!f.forSelf && !f.goalTime.trim())}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium disabled:opacity-40"
          >
            <Zap className="w-4 h-4" />
            {preview.isPending ? "Building…" : "Build the plan here"}
          </button>
          <StartRollingButton
            onStart={startRolling}
            pending={startRolling_.isPending}
            disabled={raceKm <= 0 || (!f.forSelf && !f.goalTime.trim())}
          />
          <span className="text-xs text-slate-500">
            Computed locally from your Garmin data — no AI, no API key.
          </span>
        </div>

        <p className="text-xs text-slate-500">
          The whole block at once, or one week at a time. Weekly keeps the same
          periodisation but only schedules the days ahead of you — and rebuilds each
          week against the runs you actually did.
        </p>

        {startRolling_.isError && (
          <div className="text-xs text-red-400">
            {(startRolling_.error as { response?: { data?: { detail?: string } } })
              ?.response?.data?.detail ?? String(startRolling_.error)}
          </div>
        )}

        {!f.forSelf && !f.goalTime.trim() && (
          <p className="text-xs text-amber-300/80">
            Planning for someone else needs a goal time — their paces can&apos;t come
            from your runs.
          </p>
        )}

        {preview.isError && (
          <div className="text-xs text-red-400">
            {(preview.error as { response?: { data?: { detail?: string } } })?.response
              ?.data?.detail ?? String(preview.error)}
          </div>
        )}

        {plan && (
          <div className="space-y-4 pt-1">
            <PlanTable plan={plan} adjust={adjust} onAdjust={setAdjust} />

            {f.forSelf && (
              <div className="flex items-center gap-3 flex-wrap">
                <button
                  onClick={pushToGarmin}
                  disabled={apply.isPending}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium disabled:opacity-40"
                >
                  <Upload className="w-4 h-4" />
                  {apply.isPending ? "Uploading…" : "Create & schedule in Garmin"}
                </button>
                <span className="text-xs text-slate-500 flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500/70" />
                  Writes to your Garmin account. You&apos;ll be asked to confirm.
                </span>
              </div>
            )}

            {apply.isSuccess && apply.data && (
              <div className="text-xs space-y-1">
                <div className="text-emerald-400">
                  Created {apply.data.templates_created} templates and scheduled{" "}
                  {apply.data.scheduled} sessions.
                </div>
                {apply.data.failures.map((x, i) => (
                  <div key={i} className="text-red-400">
                    {x}
                  </div>
                ))}
              </div>
            )}
            {apply.isError && (
              <div className="text-xs text-red-400">{String(apply.error)}</div>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-slate-800 pt-4">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs text-slate-400">
            Or hand it to Claude instead
          </div>
          <button
            onClick={copy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium"
          >
            {copied ? (
              <>
                <Check className="w-4 h-4" /> Copied
              </>
            ) : (
              <>
                <Copy className="w-4 h-4" /> Copy prompt
              </>
            )}
          </button>
        </div>
        <pre className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-xs text-slate-300 whitespace-pre-wrap max-h-80 overflow-y-auto">
          {prompt}
        </pre>
      </div>
    </section>
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

export function PlanPage() {
  return (
    <div className="max-w-4xl mx-auto p-4 sm:p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-50 flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-emerald-400" /> AI Plan
        </h1>
        <p className="text-slate-400 text-sm">
          Talk to Claude — with your Garmin data available as tools via MCP.
        </p>
      </header>

      <RollingPlanCard />

      <PlanBuilder />

      <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-3">
        <h2 className="text-slate-100 font-medium">How it works</h2>
        <p className="text-slate-400 text-sm">
          FitStack ships an{" "}
          <a
            href="https://modelcontextprotocol.io"
            target="_blank"
            rel="noreferrer"
            className="text-emerald-300 underline underline-offset-2"
          >
            MCP
          </a>{" "}
          server that exposes your Garmin data as tools. You chat in your existing
          Claude client (Claude Code or Claude Desktop) and Claude calls the tools
          itself — no API key stored here, no billing on FitStack, no chat UI to
          build.
        </p>
        <p className="text-slate-400 text-sm">Other things worth asking:</p>
        <ul className="text-slate-400 text-sm list-disc pl-5 space-y-1">
          <li>
            <i>&ldquo;How is my sleep score correlating with my morning HR?&rdquo;</i>
          </li>
          <li>
            <i>&ldquo;Compare my Z2 pace over the last 4 weeks.&rdquo;</i>
          </li>
          <li>
            <i>
              &ldquo;Create a threshold workout and schedule it for Thursday, then
              push it to my Vívoactive.&rdquo;
            </i>
          </li>
        </ul>
      </section>

      <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-3">
        <h2 className="text-slate-100 font-medium flex items-center gap-2">
          <Terminal className="w-4 h-4 text-emerald-400" /> Claude Code
        </h2>
        <p className="text-slate-400 text-sm">
          A <code className="text-emerald-300">.mcp.json</code> file already lives
          at the FitStack repo root. Any Claude Code session started in{" "}
          <code className="text-slate-200">C:/Users/szpyt/source/repos/fitstack</code>{" "}
          will pick it up. On first use Claude Code prompts to trust the server —
          approve it and the tools show up under <code>/mcp</code>.
        </p>
      </section>

      <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-3">
        <h2 className="text-slate-100 font-medium flex items-center gap-2">
          <MonitorSmartphone className="w-4 h-4 text-emerald-400" /> Claude Desktop
        </h2>
        <p className="text-slate-400 text-sm">
          Open{" "}
          <code className="text-emerald-300">
            %APPDATA%\Claude\claude_desktop_config.json
          </code>{" "}
          (create it if missing) and paste:
        </p>
        <pre className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-xs text-slate-300 overflow-x-auto">
          {DESKTOP_CONFIG}
        </pre>
        <p className="text-slate-400 text-sm">
          Fully quit and restart Claude Desktop. Look for the tool/hammer icon in
          the input bar — you should see <code>fitstack</code> listed with 15
          tools.
        </p>
      </section>

      <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-3">
        <h2 className="text-slate-100 font-medium flex items-center gap-2">
          <Wrench className="w-4 h-4 text-emerald-400" /> Tools exposed
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 text-sm">
          {TOOLS.map((t) => (
            <div key={t.name} className="flex items-baseline gap-2">
              <code className={t.write ? "text-amber-300" : "text-emerald-300"}>
                {t.name}
              </code>
              <span className="text-slate-500 text-xs">— {t.desc}</span>
              {t.write && (
                <span className="text-[10px] uppercase tracking-wide text-amber-500/80">
                  write
                </span>
              )}
            </div>
          ))}
        </div>
        <p className="text-slate-500 text-xs pt-2">
          Amber tools mutate Garmin state — Claude will (and should) confirm with
          you before calling them.
        </p>
      </section>
    </div>
  );
}

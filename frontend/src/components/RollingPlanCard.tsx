import { useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CalendarPlus,
  Check,
  ChevronLeft,
  ChevronRight,
  Loader2,
  TrendingDown,
  Upload,
  X,
} from "lucide-react";
import {
  useApplyPlan,
  useEndRollingPlan,
  usePlanStatus,
  usePlanWeek,
} from "@/api/hooks";
import type {
  PlanCompliance,
  PlanDecision,
  PlanSession,
  RunningWorkoutSpec,
} from "@/api/types";

const PHASE_STYLE: Record<string, string> = {
  base: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  build: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  peak: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  taper: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
  race: "bg-rose-500/15 text-rose-300 border-rose-500/30",
};

const KIND_BAR: Record<string, string> = {
  long: "bg-indigo-500/70",
  quality: "bg-emerald-500/70",
  easy: "bg-sky-500/50",
  recovery: "bg-slate-600",
  race: "bg-rose-500/80",
};

function shortDate(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${d}.${m}`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-950/60 border border-slate-800 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-slate-200 text-sm mt-0.5">{value}</div>
    </div>
  );
}

/** Last week's actual running against what it asked for.
 *
 *  The readout; `Adjusted` shows what was done about it. Kept separate so a week
 *  that fell short but did not trigger a rule still says so plainly.
 */
function LastWeek({ c }: { c: PlanCompliance }) {
  const pct = c.ratio == null ? null : Math.round(c.ratio * 100);
  const short = pct != null && pct < 70;
  const over = pct != null && pct > 130;
  const tone = short
    ? "bg-amber-500/5 border-amber-500/20 text-amber-300/90"
    : over
      ? "bg-sky-500/5 border-sky-500/20 text-sky-300/90"
      : "bg-slate-950/60 border-slate-800 text-slate-400";

  return (
    <div className={`rounded-lg border p-3 text-xs flex items-start gap-2 ${tone}`}>
      {short || over ? (
        <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
      ) : (
        <Check className="w-3 h-3 shrink-0 mt-0.5" />
      )}
      <div>
        <span className="font-medium">Week {c.week_number}:</span> you ran{" "}
        {c.actual_km} km of {c.planned_km} planned
        {pct != null && ` (${pct}%)`}, {c.runs_done} of {c.runs_planned} runs.
        {short && (
          <>
            {" "}
            Two short weeks in a row hold the next one back automatically; one on its
            own is not enough of a sample to act on.
          </>
        )}
      </div>
    </div>
  );
}

/** Why this week is lighter than the block originally said.
 *
 *  Always shows the rule that fired and the numbers behind it. Six weeks in you
 *  have to be able to answer "why was that week easier?" — an adjustment you
 *  cannot interrogate is worse than none.
 */
function Adjusted({
  d,
  originalKm,
  actualKm,
}: {
  d: PlanDecision;
  originalKm?: number | null;
  actualKm: number;
}) {
  if (d.action === "advance") return null;
  const stepBack = d.action === "step_back";
  return (
    <div
      className={`rounded-lg border p-3 text-xs space-y-1 ${
        stepBack
          ? "bg-rose-500/5 border-rose-500/20 text-rose-300/90"
          : "bg-amber-500/5 border-amber-500/20 text-amber-300/90"
      }`}
    >
      <div className="flex items-center gap-2 font-medium">
        <TrendingDown className="w-3 h-3 shrink-0" />
        {stepBack ? "Stepped back" : "Held"} —{" "}
        {originalKm != null && (
          <span className="tabular-nums">
            <span className="line-through opacity-60">{originalKm} km</span> →{" "}
            {actualKm} km
          </span>
        )}
      </div>
      {d.reasons.map((r, i) => (
        <div key={i} className="opacity-90">
          {r}
        </div>
      ))}
    </div>
  );
}

function SessionRow({ s, mode }: { s: PlanSession; mode: string }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2">
      <span
        className={`w-1 h-4 rounded-full shrink-0 ${KIND_BAR[s.kind] ?? "bg-slate-700"}`}
      />
      <span className="text-xs text-slate-500 w-14 shrink-0">
        {s.day.slice(0, 3)} {shortDate(s.date)}
      </span>
      <span className="text-sm text-slate-200 flex-1 truncate">{s.title}</span>
      <span className="text-xs text-slate-400 shrink-0 tabular-nums">
        {s.distance_km} km
      </span>
      <span className="text-xs text-slate-500 shrink-0 w-28 text-right truncate">
        {(mode === "hr" ? s.hr_label : s.pace_label) ?? s.pace_label}
      </span>
    </div>
  );
}

/** The current week of a rolling plan, or nothing when no plan is running.
 *
 *  Deliberately the default path: asking Claude for the same week costs tokens
 *  and an LLM round-trip to return what the planner computed anyway. Chat earns
 *  its place only when something the planner cannot measure — illness, travel, a
 *  niggle — should change the week.
 */
export function RollingPlanCard() {
  const status = usePlanStatus();
  const [offset, setOffset] = useState(0);
  const active = !!status.data;
  const week = usePlanWeek(offset, active);
  const apply = useApplyPlan();
  const end = useEndRollingPlan();

  if (status.isLoading) return null;
  if (!active) return null;

  const view = week.data;
  // A base block carries no race distance — that is what marks it.
  const isBase = (status.data?.race_km ?? 0) === 0;

  function scheduleWeek() {
    if (!view) return;
    const sessions = view.week.sessions
      .filter((s) => s.spec?.steps?.length)
      .map((s) => ({ date: s.date, spec: s.spec as RunningWorkoutSpec }));
    if (!sessions.length) return;
    const distinct = new Set(sessions.map((s) => JSON.stringify(s.spec))).size;
    const ok = confirm(
      `Create ${distinct} workout template${distinct === 1 ? "" : "s"} in Garmin ` +
        `and schedule ${sessions.length} session${sessions.length === 1 ? "" : "s"} ` +
        `for week ${view.week_number} (${view.week.start} to ${view.week.end})?` +
        `\n\nThis writes to your Garmin account.`,
    );
    if (ok) apply.mutate(sessions);
  }

  return (
    <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-slate-100 font-medium flex items-center gap-2">
            <CalendarClock className="w-4 h-4 text-emerald-400" />
            {status.data!.race_name ?? `${status.data!.race_km} km`} — week by week
          </h2>
          <p className="text-slate-400 text-sm mt-1">
            {isBase ? (
              <>
                {status.data!.weeks_to_race} weeks left in the block. Every run is
                capped in zone 2 and the week grows in minutes — pace is whatever the
                band gives you that day.
              </>
            ) : (
              <>
                {status.data!.weeks_to_race} weeks to race day (
                {status.data!.race_date}). Paces re-derive from your recent runs every
                time, and volume follows the ramp fixed at the start — held back only
                when two weeks running say you are not absorbing it.
              </>
            )}
          </p>
          <p className="text-slate-500 text-xs mt-1">
            {isBase ? "Different block?" : "Different race?"} Fill the form below and
            hit <span className="text-slate-400">Replace weekly plan</span>.
          </p>
        </div>
        <button
          onClick={() => {
            if (confirm("End this plan? Workouts already in Garmin are left alone."))
              end.mutate();
          }}
          disabled={end.isPending}
          className="text-xs text-slate-500 hover:text-red-400 inline-flex items-center gap-1 shrink-0"
          title="End the rolling plan"
        >
          <X className="w-3 h-3" /> End plan
        </button>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => setOffset((o) => o - 1)}
          disabled={offset <= -4}
          className="p-1 rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-30"
          title="Previous week"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="text-xs text-slate-400">
          {offset === 0 ? "Upcoming week" : offset < 0 ? `${-offset} week(s) back` : `${offset} week(s) ahead`}
        </span>
        <button
          onClick={() => setOffset((o) => o + 1)}
          disabled={offset >= 12}
          className="p-1 rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-30"
          title="Next week"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
        {week.isFetching && (
          <Loader2 className="w-3 h-3 text-slate-500 animate-spin ml-1" />
        )}
      </div>

      {week.isError && (
        <div className="text-xs text-amber-400">
          {(week.error as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? String(week.error)}
        </div>
      )}

      {view?.last_week && <LastWeek c={view.last_week} />}

      {view?.decision && (
        <Adjusted
          d={view.decision}
          originalKm={view.original_planned_km}
          actualKm={view.week.planned_km}
        />
      )}

      {view && (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${
                PHASE_STYLE[view.week.phase] ?? ""
              }`}
            >
              {view.week.phase}
            </span>
            <span className="text-sm text-slate-200">
              Week {view.week_number} of {view.weeks_total}
            </span>
            <span className="text-xs text-slate-500">
              {view.week.start} — {view.week.end}
            </span>
            {view.week.down_week && (
              <span className="text-[10px] uppercase tracking-wide text-emerald-400">
                down week
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat
              label={view.week.planned_minutes ? "Time" : "Volume"}
              value={
                view.week.planned_minutes
                  ? `${Math.round(view.week.planned_minutes / 60)}h ${
                      view.week.planned_minutes % 60
                    }m`
                  : `${view.week.volume_km} km`
              }
            />
            <Stat label="Sessions" value={String(view.week.sessions.length)} />
            <Stat
              label={view.target_mode === "hr" ? "Zone" : "Threshold"}
              value={
                view.target_mode === "hr" && view.hr_basis
                  ? (view.hr_basis.zones.easy ?? `${view.hr_basis.max_hr} bpm`)
                  : view.basis.threshold_pace
              }
            />
            <Stat label="Weeks left" value={String(view.weeks_remaining_after_this)} />
          </div>

          <div className="rounded-lg bg-slate-950/60 border border-slate-800 divide-y divide-slate-800">
            {view.week.sessions.map((s) => (
              <SessionRow key={s.date} s={s} mode={view.target_mode} />
            ))}
          </div>

          {view.basis.reference && (
            <p className="text-xs text-slate-500">
              Paces from {view.basis.reference}.
            </p>
          )}

          {view.warnings.length > 0 && (
            <ul className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-3 space-y-1.5">
              {view.warnings.map((w, i) => (
                <li key={i} className="text-xs text-amber-300/90 flex gap-2">
                  <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
                  {w}
                </li>
              ))}
            </ul>
          )}

          <div className="flex items-center gap-3 flex-wrap">
            <button
              onClick={scheduleWeek}
              disabled={apply.isPending}
              className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm inline-flex items-center gap-2"
            >
              <Upload className="w-4 h-4" />
              {apply.isPending ? "Uploading…" : "Schedule this week in Garmin"}
            </button>
            <span className="text-xs text-slate-500 inline-flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" />
              Writes to your Garmin account. You&apos;ll be asked to confirm.
            </span>
          </div>

          {apply.isSuccess && apply.data && (
            <div className="space-y-1">
              <div className="text-xs text-emerald-400">
                Created {apply.data.templates_created} template
                {apply.data.templates_created === 1 ? "" : "s"} and scheduled{" "}
                {apply.data.scheduled} session
                {apply.data.scheduled === 1 ? "" : "s"}.
              </div>
              {apply.data.failures.map((x, i) => (
                <div key={i} className="text-xs text-red-400">
                  {x}
                </div>
              ))}
            </div>
          )}
          {apply.isError && (
            <div className="text-xs text-red-400">{String(apply.error)}</div>
          )}
        </>
      )}
    </section>
  );
}

/** Shown in the builder when no plan is running — the entry point to weekly mode. */
export function StartRollingButton({
  onStart,
  pending,
  disabled,
}: {
  onStart: () => void;
  pending: boolean;
  disabled: boolean;
}) {
  const status = usePlanStatus();
  const active = !!status.data;
  return (
    <button
      onClick={onStart}
      disabled={disabled || pending}
      className="px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 hover:bg-slate-700 hover:border-emerald-600 disabled:opacity-50 text-slate-200 text-sm inline-flex items-center gap-2"
      title={
        active
          ? "Rebuild the weekly plan from the form above — replaces the one running"
          : "Compute the whole block but take it one week at a time"
      }
    >
      <CalendarPlus className="w-4 h-4" />
      {pending
        ? "Starting…"
        : active
          ? "Replace weekly plan"
          : "Start weekly plan"}
    </button>
  );
}

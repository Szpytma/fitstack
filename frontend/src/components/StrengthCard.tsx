import { useState } from "react";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Dumbbell,
  Loader2,
  Upload,
  X,
} from "lucide-react";
import {
  useApplyStrength,
  useDisableStrength,
  useEnableStrength,
  usePlanStatus,
  useStrengthWeek,
} from "@/api/hooks";
import type { StrengthSession, StrengthWorkoutSpec } from "@/api/types";

const DAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

const FOCUS_STYLE: Record<string, string> = {
  lower: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  upper: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  upper_light: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
};

function shortDate(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${d}.${m}`;
}

function SessionBlock({ s }: { s: StrengthSession }) {
  return (
    <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-slate-500 w-16 shrink-0">
          {s.day.slice(0, 3)} {shortDate(s.date)}
        </span>
        <span
          className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${
            FOCUS_STYLE[s.focus] ?? ""
          }`}
        >
          {s.focus_label}
        </span>
        {s.estimated_duration_s != null && (
          <span className="text-xs text-slate-500 ml-auto">
            ~{Math.round(s.estimated_duration_s / 60)} min
          </span>
        )}
      </div>
      <div className="divide-y divide-slate-800/70">
        {s.warmup && (
          <div className="flex items-center gap-3 py-1.5 text-sm">
            <span className="text-slate-400 flex-1 truncate">
              {s.warmup.exercise_name}
              <span className="text-slate-600"> · rozgrzewka</span>
            </span>
            <span className="text-slate-400 tabular-nums shrink-0">
              {Math.round(s.warmup.duration_s / 60)} min
            </span>
            <span className="w-16 shrink-0" />
          </div>
        )}
        {s.exercises.map((e) => (
          <div
            key={e.exercise_name}
            className="flex items-center gap-3 py-1.5 text-sm"
          >
            <span className="text-slate-200 flex-1 truncate">
              {e.exercise_name}
            </span>
            <span className="text-slate-400 tabular-nums shrink-0">
              {e.sets}×{e.reps}
            </span>
            <span className="text-xs text-slate-600 w-16 text-right shrink-0">
              {e.rest_s}s
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** The strength week that sits alongside the running one.
 *
 *  Shares the running plan's anchor, so there is no separate start or stop here
 *  — only which days it lands on. Shown only once a plan is running, because a
 *  strength block without one has no dates to hang off.
 */
export function StrengthCard() {
  const status = usePlanStatus();
  const [offset, setOffset] = useState(0);
  const [picking, setPicking] = useState(false);
  const [days, setDays] = useState<string[]>(["Wednesday", "Friday", "Sunday"]);

  const hasPlan = !!status.data;
  const week = useStrengthWeek(offset, hasPlan);
  const enable = useEnableStrength();
  const disable = useDisableStrength();
  const apply = useApplyStrength();

  if (!hasPlan) return null;

  const view = week.data;
  const attached = !!view;
  const notFound =
    week.isError &&
    (week.error as { response?: { status?: number } })?.response?.status === 404;

  function scheduleWeek() {
    if (!view) return;
    const sessions = view.week.sessions
      .filter((s) => s.spec?.exercises?.length)
      .map((s) => ({ date: s.date, spec: s.spec as StrengthWorkoutSpec }));
    if (!sessions.length) return;
    const ok = confirm(
      `Create ${sessions.length} strength workouts in Garmin and schedule them ` +
        `for week ${view.week_number} (${view.week.start} to ${view.week.end})?` +
        `\n\nAny strength workouts already scheduled in that range are removed first.` +
        `\n\nThis writes to your Garmin account.`,
    );
    if (ok) apply.mutate(sessions);
  }

  return (
    <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-slate-100 font-medium flex items-center gap-2">
            <Dumbbell className="w-4 h-4 text-amber-400" /> Strength
          </h2>
          <p className="text-slate-400 text-sm mt-1">
            {attached
              ? `${view!.days.join(", ")} — lift in the evening, run in the morning, so rest days stay rest days.`
              : "Three sessions a week on your running days. No loaded leg work on long-run day."}
          </p>
        </div>
        {attached && (
          <button
            onClick={() => {
              if (confirm("Detach the strength block? Garmin is left untouched."))
                disable.mutate();
            }}
            disabled={disable.isPending}
            className="text-xs text-slate-500 hover:text-red-400 inline-flex items-center gap-1 shrink-0"
          >
            <X className="w-3 h-3" /> Detach
          </button>
        )}
      </div>

      {(notFound || picking) && (
        <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 space-y-3">
          <div className="text-xs text-slate-400">Gym days</div>
          <div className="flex flex-wrap gap-2">
            {DAYS.map((d) => {
              const on = days.includes(d);
              return (
                <button
                  key={d}
                  onClick={() =>
                    setDays((prev) =>
                      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d],
                    )
                  }
                  className={`px-2.5 py-1 rounded text-xs border ${
                    on
                      ? "bg-amber-600 border-amber-500 text-white"
                      : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                  }`}
                >
                  {d.slice(0, 3)}
                </button>
              );
            })}
          </div>
          <button
            onClick={() => {
              enable.mutate(days);
              setPicking(false);
            }}
            disabled={!days.length || enable.isPending}
            className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm"
          >
            {enable.isPending ? "Attaching…" : attached ? "Move days" : "Attach strength block"}
          </button>
        </div>
      )}

      {attached && (
        <>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setOffset((o) => o - 1)}
              disabled={offset <= -4}
              className="p-1 rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-30"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-sm text-slate-200">
              Week {view!.week_number} of {view!.weeks_total}
            </span>
            <span className="text-xs text-slate-500">
              {view!.week.sets}×{view!.week.reps}
            </span>
            {view!.week.deload && (
              <span className="text-[10px] uppercase tracking-wide text-emerald-400">
                deload
              </span>
            )}
            <button
              onClick={() => setOffset((o) => o + 1)}
              disabled={offset >= 20}
              className="p-1 rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-30"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
            {week.isFetching && (
              <Loader2 className="w-3 h-3 text-slate-500 animate-spin" />
            )}
            <button
              onClick={() => setPicking((p) => !p)}
              className="text-xs text-slate-500 hover:text-amber-300 ml-auto"
            >
              Change days
            </button>
          </div>

          {view!.week.note && (
            <p className="text-xs text-slate-500">{view!.week.note}</p>
          )}

          <div className="space-y-2">
            {view!.week.sessions.map((s) => (
              <SessionBlock key={s.date} s={s} />
            ))}
          </div>

          <ul className="text-xs text-slate-500 space-y-1">
            {view!.notes.map((n, i) => (
              <li key={i}>· {n}</li>
            ))}
          </ul>

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
              Replaces strength workouts already in that week.
            </span>
          </div>

          {apply.isSuccess && apply.data && (
            <div className="space-y-1">
              <div className="text-xs text-emerald-400">
                Created {apply.data.created}, scheduled {apply.data.scheduled}
                {apply.data.removed > 0 && `, removed ${apply.data.removed} existing`}.
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

      {week.isError && !notFound && (
        <div className="text-xs text-amber-400">
          {(week.error as { response?: { data?: { detail?: string } } })?.response
            ?.data?.detail ?? String(week.error)}
        </div>
      )}
    </section>
  );
}

import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Info, Minus, Plus, RotateCcw } from "lucide-react";
import type { PlanSession, PlanTargetMode, PlanWeek, RacePlan } from "@/api/types";
import { adjustedSession, deltaFor, hasAnyAdjust, NO_ADJUST, type PlanAdjust } from "@/lib/planAdjust";

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

function fmtMin(s: number): string {
  const m = Math.round(s / 60);
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

interface RowProps {
  s: PlanSession;
  mode: PlanTargetMode;
  adjust: PlanAdjust;
  onNudge?: (date: string, by: number) => void;
}

function SessionRow({ s, mode, adjust, onNudge }: RowProps) {
  const { label, delta } = adjustedSession(s, mode, adjust);
  const unit = mode === "hr" ? "bpm" : "s/km";
  // Race day has no workout to retarget.
  const editable = onNudge && s.spec != null;

  return (
    <li className="flex items-center gap-2 text-xs py-0.5 group/row">
      <span className={`w-1 h-4 rounded-full shrink-0 ${KIND_BAR[s.kind] ?? "bg-slate-700"}`} />
      <span className="w-8 shrink-0 text-slate-500">{s.day.slice(0, 3)}</span>
      <span className="flex-1 min-w-0 truncate text-slate-200">{s.title}</span>
      <span className="w-16 shrink-0 text-right tabular-nums text-slate-400">
        {s.distance_km} km
      </span>
      <span className="w-12 shrink-0 text-right tabular-nums text-slate-500">
        {fmtMin(s.duration_s)}
      </span>
      {/* In HR mode the bpm band is what the watch enforces, so it leads; the
          pace that sized the session is kept on hover. */}
      <span
        className={`w-32 shrink-0 text-right hidden sm:block truncate ${
          delta !== 0 ? "text-emerald-300" : "text-slate-500"
        }`}
        title={
          delta !== 0
            ? `Adjusted ${delta > 0 ? "+" : ""}${delta} ${unit} from ${s.hr_label ?? s.pace_label}`
            : s.hr_label
              ? `Sized from pace ${s.pace_label}`
              : undefined
        }
      >
        {label ?? s.hr_label ?? s.pace_label}
      </span>

      {editable && (
        <span className="shrink-0 flex items-center gap-0.5 opacity-0 group-hover/row:opacity-100 focus-within:opacity-100 transition-opacity">
          <button
            onClick={() => onNudge(s.date, -(mode === "hr" ? 5 : 5))}
            title={`Easier by 5 ${unit}`}
            aria-label={`Make ${s.title} easier`}
            className="p-0.5 rounded text-slate-600 hover:bg-slate-800 hover:text-sky-400"
          >
            <Minus className="w-3 h-3" />
          </button>
          <button
            onClick={() => onNudge(s.date, mode === "hr" ? 5 : 5)}
            title={`Harder by 5 ${unit}`}
            aria-label={`Make ${s.title} harder`}
            className="p-0.5 rounded text-slate-600 hover:bg-slate-800 hover:text-amber-400"
          >
            <Plus className="w-3 h-3" />
          </button>
        </span>
      )}
    </li>
  );
}

function WeekRow({
  w,
  defaultOpen,
  mode,
  adjust,
  onNudge,
}: {
  w: PlanWeek;
  defaultOpen: boolean;
  mode: PlanTargetMode;
  adjust: PlanAdjust;
  onNudge?: (date: string, by: number) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const touched = w.sessions.some((s) => deltaFor(adjust, s.date) !== 0);
  return (
    <div className="px-3 py-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 text-left group"
      >
        {open ? (
          <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 shrink-0" />
        )}
        <span className="text-slate-300 text-sm font-medium w-16 shrink-0">
          Week {w.index}
        </span>
        <span
          className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border shrink-0 ${
            PHASE_STYLE[w.phase] ?? ""
          }`}
        >
          {w.phase}
        </span>
        {w.down_week && (
          <span className="text-[10px] uppercase tracking-wide text-slate-500 shrink-0">
            down
          </span>
        )}
        <span className="text-slate-500 text-xs truncate hidden md:block">
          {w.start} → {w.end}
        </span>
        {touched && (
          <span className="text-[10px] uppercase tracking-wide text-emerald-400 shrink-0">
            adjusted
          </span>
        )}
        <span className="ml-auto text-slate-300 text-sm tabular-nums shrink-0">
          {w.volume_km} km
        </span>
      </button>
      {open && (
        <ul className="mt-2 ml-6 pl-3 border-l border-slate-800">
          {w.sessions.map((s, i) => (
            <SessionRow key={i} s={s} mode={mode} adjust={adjust} onNudge={onNudge} />
          ))}
        </ul>
      )}
    </div>
  );
}

export function PlanTable({
  plan,
  adjust = NO_ADJUST,
  onAdjust,
}: {
  plan: RacePlan;
  adjust?: PlanAdjust;
  onAdjust?: (next: PlanAdjust) => void;
}) {
  const paceOrder = ["recovery", "easy", "long", "threshold", "interval", "race"];
  const mode = plan.target_mode;
  const unit = mode === "hr" ? "bpm" : "s/km";

  const nudgeGlobal = (by: number) =>
    onAdjust?.({ ...adjust, global: adjust.global + by });

  const nudgeSession = (date: string, by: number) =>
    onAdjust?.({
      ...adjust,
      perSession: { ...adjust.perSession, [date]: (adjust.perSession[date] ?? 0) + by },
    });

  const reset = () => onAdjust?.(NO_ADJUST);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Weeks" value={String(plan.weeks_total)} />
        <Stat label="Total" value={`${plan.total_km} km`} />
        <Stat label="Peak week" value={`${plan.peak_week_km} km`} />
        <Stat
          label="Projected"
          value={plan.basis.projected_race_time ?? "—"}
        />
      </div>

      <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-4 space-y-2">
        <div className="flex items-start gap-2">
          <Info className="w-4 h-4 text-slate-500 mt-0.5 shrink-0" />
          <div className="text-xs text-slate-400 space-y-1">
            <div>
              Paces derive from a threshold of{" "}
              <span className="text-slate-200">{plan.basis.threshold_pace}</span>
              {plan.basis.source === "goal_time" ? (
                <> , set by your goal time.</>
              ) : plan.basis.reference ? (
                <>
                  , estimated from your best recent effort —{" "}
                  <span className="text-slate-200">{plan.basis.reference}</span>.
                </>
              ) : (
                <>.</>
              )}
            </div>
            {plan.basis.weekly_km_start != null && (
              <div>
                Built from{" "}
                <span className="text-slate-200">
                  {plan.basis.weekly_km_start} km/week
                </span>
                {plan.basis.volume_basis?.median_km != null && (
                  <>
                    {" "}
                    — median of the weeks you ran is{" "}
                    {plan.basis.volume_basis.median_km} km, best recent week{" "}
                    {plan.basis.volume_basis.best_km} km
                    {plan.basis.volume_basis.longest_run_km != null && (
                      <>, longest run {plan.basis.volume_basis.longest_run_km} km</>
                    )}
                  </>
                )}
                .
              </div>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-xs">
          {paceOrder
            .filter((k) => plan.basis.paces[k])
            .map((k) => (
              <span key={k} className="text-slate-500">
                <span className="capitalize">{k}</span>{" "}
                <span className="text-slate-300">{plan.basis.paces[k]}</span>
              </span>
            ))}
        </div>

        {/* Paces stay visible in HR mode: they are still what set every distance
            and duration below — the watch just chases bpm instead. */}
        {plan.target_mode === "hr" && plan.hr_basis && (
          <div className="pt-2 mt-2 border-t border-slate-800 space-y-1">
            <div className="text-xs text-slate-400">
              Sessions are targeted by <span className="text-red-400">heart rate</span>,
              from a max HR of{" "}
              <span className="text-slate-200">{plan.hr_basis.max_hr} bpm</span>
              {plan.hr_basis.source === "garmin_zones" ? (
                <>
                  {" "}
                  — your configured Garmin zones
                  {plan.hr_basis.resting_hr != null && (
                    <>, resting {plan.hr_basis.resting_hr} bpm</>
                  )}
                  .
                </>
              ) : plan.hr_basis.source === "garmin_max_hr" ? (
                <> — set in Garmin Connect, split into zones by percentage.</>
              ) : plan.hr_basis.reference ? (
                <>
                  {" "}
                  — estimated from your runs, highest seen in{" "}
                  <span className="text-slate-200">{plan.hr_basis.reference}</span>.
                </>
              ) : (
                <> — estimated from your recent runs.</>
              )}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
              {Object.entries(plan.hr_basis.zones).map(([k, v]) => (
                <span key={k} className="text-slate-500">
                  <span className="capitalize">{k}</span>{" "}
                  <span className="text-slate-300">{v}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {onAdjust && (
        <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 flex flex-wrap items-center gap-3">
          <span className="text-xs text-slate-400">
            Adjust every session
            <span className="text-slate-600"> · hover a row to tune one</span>
          </span>
          <div className="inline-flex items-center gap-1">
            <button
              onClick={() => nudgeGlobal(-5)}
              title={`Easier by 5 ${unit}`}
              className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-sky-300 text-xs"
            >
              − easier
            </button>
            <span
              className={`px-2 text-xs tabular-nums ${
                adjust.global !== 0 ? "text-emerald-300" : "text-slate-500"
              }`}
            >
              {adjust.global > 0 ? "+" : ""}
              {adjust.global} {unit}
            </span>
            <button
              onClick={() => nudgeGlobal(5)}
              title={`Harder by 5 ${unit}`}
              className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-amber-300 text-xs"
            >
              + harder
            </button>
          </div>
          {hasAnyAdjust(adjust) && (
            <button
              onClick={reset}
              className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
            >
              <RotateCcw className="w-3 h-3" /> Reset
            </button>
          )}
          {hasAnyAdjust(adjust) && (
            <span className="text-[11px] text-emerald-400/80 ml-auto">
              Adjustments apply when you push to Garmin.
            </span>
          )}
        </div>
      )}

      {plan.warnings.length > 0 && (
        <ul className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-3 space-y-1.5">
          {plan.warnings.map((w, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-amber-200/90">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-400" />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="rounded-lg bg-slate-900 border border-slate-800 divide-y divide-slate-800 max-h-[28rem] overflow-y-auto">
        {plan.weeks.map((w, i) => (
          <WeekRow
            key={w.index}
            w={w}
            defaultOpen={i === 0}
            mode={mode}
            adjust={adjust}
            onNudge={onAdjust ? nudgeSession : undefined}
          />
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-950/60 border border-slate-800 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-slate-100 font-medium tabular-nums">{value}</div>
    </div>
  );
}

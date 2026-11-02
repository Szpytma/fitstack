import {
  useSleepHistory,
  useStatsOverview,
  useStatsWeeks,
  useSummaryHistory,
  useWeightHistory,
} from "@/api/hooks";
import type { ReadinessFactor, StatsWeek, WeightPoint } from "@/api/types";
import { StatCard } from "@/components/StatCard";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Gauge } from "lucide-react";

/** The project's chart palette. Emerald-500 fails the dark-surface lightness
 *  band, so bars use emerald-600; HR and anything critical is red-500. */
const ACCENT = "#059669";
const MUTED = "#475569";
const BAD = "#ef4444";
const GRID = "#334155";
const AXIS = "#64748b";
const TOOLTIP = { background: "#0f172a", border: "1px solid #334155" } as const;

const DAY_WINDOW = 35;

/** Seconds to h:mm:ss, or m:ss under the hour. */
function hms(sec: number | null | undefined): string {
  if (!sec) return "—";
  const t = Math.round(sec);
  const mm = String(Math.floor(t / 60) % 60).padStart(2, "0");
  const ss = String(t % 60).padStart(2, "0");
  return t >= 3600 ? `${Math.floor(t / 3600)}:${mm}:${ss}` : `${Math.floor(t / 60)}:${ss}`;
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const a = [...xs].sort((p, q) => p - q);
  const mid = Math.floor(a.length / 2);
  return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
}

function round1(x: number | null | undefined): string {
  return x == null ? "—" : x.toFixed(1);
}

/** Readiness factor keys are Garmin's; these are what they mean. */
const FACTOR_LABELS: Record<string, string> = {
  recovery_time: "Recovery time",
  hrv: "HRV",
  stress_history: "Stress history",
  sleep_score: "Sleep score",
  sleep_history: "Sleep history",
  acwr: "Load ratio",
};

const BUCKET_LABELS: Record<string, string> = {
  aerobic_low: "Low aerobic",
  aerobic_high: "High aerobic",
  anaerobic: "Anaerobic",
};

const AGE_COMPONENT_LABELS: Record<string, string> = {
  bmi: "BMI",
  rhr: "Resting HR",
  vigorousDaysAvg: "Vigorous days / week",
  vigorousMinutesAvg: "Vigorous minutes / week",
};

function Card({
  title,
  note,
  children,
  wide,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <section
      className={
        "rounded-xl bg-slate-900 border border-slate-800 p-5 min-w-0 " +
        (wide ? "lg:col-span-2" : "")
      }
    >
      <h2 className="text-slate-200 font-semibold">{title}</h2>
      {note && <p className="text-slate-500 text-xs mt-1 max-w-prose">{note}</p>}
      <div className="mt-4 min-w-0">{children}</div>
    </section>
  );
}

function Empty({ label }: { label: string }) {
  return <div className="text-slate-500 text-sm py-8 text-center">{label}</div>;
}

export function StatsPage() {
  const overview = useStatsOverview();
  const weight = useWeightHistory(180);
  const weeks = useStatsWeeks(24);
  const summaries = useSummaryHistory(DAY_WINDOW);
  const sleep = useSleepHistory(DAY_WINDOW);

  const o = overview.data;
  const ts = o?.training_status;
  const hrv = o?.hrv;
  const ready = o?.readiness;
  const age = o?.fitness_age;
  const races = o?.race_predictions;

  // Recovery series: two endpoints, one row per day, oldest first.
  const sleepByDay = new Map((sleep.data ?? []).map((s) => [s.date, s]));
  const recovery = (summaries.data ?? [])
    .slice()
    .reverse()
    .map((d) => {
      const s = sleepByDay.get(d.date);
      return {
        date: d.date.slice(5),
        rhr: d.resting_hr ?? null,
        hours: s?.sleep_seconds ? Number((s.sleep_seconds / 3600).toFixed(1)) : null,
        score: s?.sleep_score ?? null,
      };
    });

  const sleep7 = median(
    recovery.slice(-7).map((r) => r.hours).filter((h): h is number => h != null),
  );
  // Baseline is the early part of the window, so a bad fortnight cannot move it.
  const rhrBase = median(
    recovery
      .slice(0, Math.max(1, recovery.length - 12))
      .map((r) => r.rhr)
      .filter((v): v is number => v != null),
  );

  const efWeeks = (weeks.data ?? []).filter((w) => w.ef_median != null);
  const latestEf = efWeeks.at(-1) ?? null;
  const blockStartEf = efWeeks.find((w) => w.week_no != null)?.ef_median ?? null;
  const efDelta =
    latestEf?.ef_median != null && blockStartEf
      ? ((latestEf.ef_median - blockStartEf) / blockStartEf) * 100
      : null;

  const blockWeeks = (weeks.data ?? []).filter((w) => w.week_no != null);
  const points: WeightPoint[] = weight.data?.points ?? [];
  const latestWeight = points.at(-1) ?? null;
  const bmi30 = weight.data?.bmi30_kg ?? null;
  const bmiPriority = age?.components.find((c) => c.priority === 1);

  if (overview.isLoading) {
    return <div className="max-w-6xl mx-auto p-4 sm:p-6 text-slate-500 text-sm">Loading…</div>;
  }

  if (overview.isError) {
    return (
      <div className="max-w-6xl mx-auto p-4 sm:p-6 text-slate-400 text-sm">
        Could not read training metrics from Garmin.
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-6">
      <header className="flex items-baseline justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-slate-50 flex items-center gap-2">
            <Gauge className="w-5 h-5 text-slate-400" /> Stats
          </h1>
          <p className="text-slate-400 text-sm">
            Everything Garmin computes, as of {o?.date ?? "—"}
          </p>
        </div>
        {overview.isFetching && <span className="text-xs text-slate-500">refreshing…</span>}
      </header>

      {!!o?.warnings.length && (
        <div className="rounded-lg border border-yellow-900/60 bg-yellow-950/30 px-4 py-3 text-xs text-yellow-200/80">
          Some metrics did not load: {o.warnings.join("; ")}
        </div>
      )}

      <div className="grid gap-4 grid-cols-2 lg:grid-cols-5">
        <StatCard
          label="Weight"
          value={latestWeight ? `${round1(latestWeight.weight_kg)} kg` : "—"}
          sub={
            latestWeight
              ? `BMI ${round1(latestWeight.bmi)} · weighed ${latestWeight.day}`
              : "no weigh-ins"
          }
        />
        <StatCard
          label="Efficiency factor"
          value={latestEf?.ef_median?.toFixed(3) ?? "—"}
          sub={
            efDelta != null
              ? `${efDelta >= 0 ? "+" : "−"}${Math.abs(efDelta).toFixed(1)}% since block start`
              : "m/min/beat"
          }
        />
        <StatCard
          label="VO₂max"
          value={ts?.vo2max != null ? round1(ts.vo2max) : "—"}
          sub={ts?.vo2max_measured ? `measured ${ts.vo2max_measured}` : undefined}
        />
        <StatCard
          label="HRV, weekly"
          value={hrv?.weekly_avg != null ? `${hrv.weekly_avg} ms` : "—"}
          sub={
            hrv?.baseline_balanced_low != null
              ? `${hrv.status ?? "—"} · balanced ${hrv.baseline_balanced_low}–${hrv.baseline_balanced_high}`
              : (hrv?.status ?? undefined)
          }
        />
        <StatCard
          label="Sleep, 7 nights"
          value={sleep7 != null ? `${round1(sleep7)} h` : "—"}
          sub={
            ready?.score != null
              ? `readiness ${ready.score} ${ready.level ?? ""}`.trim()
              : undefined
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Weight"
          note={
            bmi30
              ? `Manual weigh-ins. The dashed line is ${round1(bmi30)} kg — BMI 30 at ${round1(weight.data?.height_cm)} cm, the obesity threshold.${bmiPriority ? " Garmin ranks BMI as the component holding fitness age back hardest." : ""}`
              : "Manual weigh-ins over the last 180 days."
          }
        >
          {weight.isLoading ? (
            <Empty label="Loading…" />
          ) : points.length < 2 ? (
            <Empty label="Not enough weigh-ins to draw a trend." />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={points} margin={{ left: 0, right: 12, top: 8, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="day" stroke={AXIS} fontSize={11} tickFormatter={(d) => d.slice(5)} />
                <YAxis
                  stroke={AXIS}
                  fontSize={11}
                  domain={["dataMin - 2", "dataMax + 2"]}
                  tickFormatter={(v) => v.toFixed(0)}
                  width={38}
                />
                <Tooltip
                  contentStyle={TOOLTIP}
                  formatter={(v: number, k) => [k === "weight_kg" ? `${v} kg` : v, "Weight"]}
                />
                {bmi30 != null && (
                  <ReferenceLine
                    y={bmi30}
                    stroke={BAD}
                    strokeDasharray="4 4"
                    label={{ value: `BMI 30 · ${round1(bmi30)} kg`, fill: AXIS, fontSize: 10, position: "insideTopLeft" }}
                  />
                )}
                <Line
                  type="linear"
                  dataKey="weight_kg"
                  stroke={ACCENT}
                  strokeWidth={2}
                  dot={{ r: 3, fill: ACCENT }}
                  name="Weight"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card
          title="Efficiency factor by week"
          note="Metres per minute per heartbeat, aerobic runs only, median of the week. Rising at a fixed heart rate is the base block working. Lighter bars are before the block — EF is only comparable inside one training era."
        >
          {weeks.isLoading ? (
            <Empty label="Loading…" />
          ) : efWeeks.length === 0 ? (
            <Empty label="No aerobic runs in this window." />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={efWeeks} margin={{ left: 0, right: 8, top: 8, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis
                  dataKey="week_start"
                  stroke={AXIS}
                  fontSize={10}
                  tickFormatter={(d) => d.slice(5)}
                  interval="preserveStartEnd"
                  minTickGap={24}
                />
                <YAxis
                  stroke={AXIS}
                  fontSize={11}
                  domain={["dataMin - 0.03", "dataMax + 0.02"]}
                  tickFormatter={(v) => v.toFixed(2)}
                  width={38}
                />
                <Tooltip
                  contentStyle={TOOLTIP}
                  labelFormatter={(d) => `Week of ${d}`}
                  formatter={(v: number, _k, p) => [
                    `${v.toFixed(3)} (${(p.payload as StatsWeek).ef_runs} of ${(p.payload as StatsWeek).runs} runs)`,
                    "EF",
                  ]}
                />
                <Bar dataKey="ef_median" radius={[3, 3, 0, 0]} name="EF">
                  {efWeeks.map((w) => (
                    <Cell key={w.week_start} fill={w.week_no != null ? ACCENT : MUTED} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <Card
        title="Planned against actual"
        note="Minutes, not kilometres — at a fixed heart rate distance is an outcome, not the task. Planned volume is the active block replayed off its anchor, so it matches the calendar. Red means the week came in under 70% of plan."
        wide
      >
        {blockWeeks.length === 0 ? (
          <Empty label="No active plan covers this window." />
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={blockWeeks} margin={{ left: 0, right: 8, top: 8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
              <XAxis
                dataKey="week_no"
                stroke={AXIS}
                fontSize={11}
                tickFormatter={(n) => `W${n}`}
              />
              <YAxis stroke={AXIS} fontSize={11} width={38} />
              <Tooltip
                contentStyle={TOOLTIP}
                labelFormatter={(n) => `Week ${n}`}
                formatter={(v: number, k) => [
                  `${v} min`,
                  k === "planned_minutes" ? "Planned" : "Actual",
                ]}
              />
              <Bar dataKey="planned_minutes" fill={MUTED} radius={[3, 3, 0, 0]} name="Planned" />
              <Bar dataKey="actual_minutes" radius={[3, 3, 0, 0]} name="Actual">
                {blockWeeks.map((w) => (
                  <Cell
                    key={w.week_start}
                    fill={
                      w.planned_minutes && w.actual_minutes < w.planned_minutes * 0.7
                        ? BAD
                        : ACCENT
                    }
                  />
                ))}
              </Bar>
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title={`Sleep, last ${DAY_WINDOW} nights`}
          note="One bar per night against a 7.5 hour line. Red is a sleep score under 50."
        >
          {sleep.isLoading ? (
            <Empty label="Loading…" />
          ) : recovery.length === 0 ? (
            <Empty label="No sleep records in this window." />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={recovery} margin={{ left: 0, right: 8, top: 8, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="date" stroke={AXIS} fontSize={10} minTickGap={20} />
                <YAxis stroke={AXIS} fontSize={11} width={32} />
                <Tooltip
                  contentStyle={TOOLTIP}
                  formatter={(v: number, _k, p) => [
                    `${v} h (score ${(p.payload as { score: number | null }).score ?? "—"})`,
                    "Sleep",
                  ]}
                />
                <ReferenceLine y={7.5} stroke={AXIS} strokeDasharray="4 4" />
                <Bar dataKey="hours" radius={[2, 2, 0, 0]} name="Sleep">
                  {recovery.map((r, i) => (
                    <Cell
                      key={i}
                      fill={r.score == null ? MUTED : r.score >= 50 ? ACCENT : BAD}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card
          title={`Resting heart rate, last ${DAY_WINDOW} days`}
          note={
            rhrBase != null
              ? `The dashed line is ${rhrBase} bpm, the median of the earlier part of this window. It answers one bad night faster than it answers training load.`
              : "Daily resting heart rate."
          }
        >
          {summaries.isLoading ? (
            <Empty label="Loading…" />
          ) : recovery.every((r) => r.rhr == null) ? (
            <Empty label="No resting heart rate in this window." />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={recovery} margin={{ left: 0, right: 8, top: 8, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="date" stroke={AXIS} fontSize={10} minTickGap={20} />
                <YAxis
                  stroke={AXIS}
                  fontSize={11}
                  width={32}
                  domain={["dataMin - 3", "dataMax + 3"]}
                />
                <Tooltip contentStyle={TOOLTIP} formatter={(v: number) => [`${v} bpm`, "Resting HR"]} />
                {rhrBase != null && (
                  <ReferenceLine y={rhrBase} stroke={AXIS} strokeDasharray="4 4" />
                )}
                <Line
                  type="linear"
                  dataKey="rhr"
                  stroke={BAD}
                  strokeWidth={2}
                  dot={{ r: 2, fill: BAD }}
                  connectNulls
                  name="Resting HR"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Training load balance"
          note={
            ts?.balance_feedback
              ? `Four-week load against the range Garmin wants. Garmin says: ${ts.balance_feedback.toLowerCase().replace(/_/g, " ")}.`
              : "Four-week load against the range Garmin wants."
          }
        >
          {!ts?.load_balance.length ? (
            <Empty label="No load balance available." />
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart
                layout="vertical"
                data={ts.load_balance}
                margin={{ left: 8, right: 16, top: 8, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
                <XAxis type="number" stroke={AXIS} fontSize={11} />
                <YAxis
                  type="category"
                  dataKey="bucket"
                  stroke={AXIS}
                  fontSize={11}
                  width={92}
                  tickFormatter={(b: string) => BUCKET_LABELS[b] ?? b}
                />
                <Tooltip
                  contentStyle={TOOLTIP}
                  labelFormatter={(b: string) => BUCKET_LABELS[b] ?? b}
                  formatter={(v: number, _k, p) => {
                    const r = p.payload as { target_min: number; target_max: number };
                    return [`${Math.round(v)} (target ${r.target_min}–${r.target_max})`, "Load"];
                  }}
                />
                {ts.load_balance.map((b) =>
                  b.target_min != null && b.target_max != null ? (
                    <ReferenceArea
                      key={b.bucket}
                      x1={b.target_min}
                      x2={b.target_max}
                      y1={b.bucket}
                      y2={b.bucket}
                      fill={AXIS}
                      fillOpacity={0.18}
                      stroke="none"
                    />
                  ) : null,
                )}
                <Bar dataKey="load" radius={[0, 3, 3, 0]} barSize={18} name="Load">
                  {ts.load_balance.map((b) => (
                    <Cell
                      key={b.bucket}
                      fill={
                        b.load != null &&
                        b.target_min != null &&
                        b.target_max != null &&
                        (b.load > b.target_max || b.load < b.target_min)
                          ? BAD
                          : ACCENT
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card
          title="Readiness, on waking"
          note={
            ready?.latest_recovery_time_min
              ? `What the morning score is made of. The day's latest reading is ${ready.latest_score ?? "—"} with ${Math.round(ready.latest_recovery_time_min / 60)} h of recovery left — that reflects today's session, not how recovered you are.`
              : "What the morning readiness score is made of. The lowest bar is the limiter."
          }
        >
          {!ready?.factors.length ? (
            <Empty label="No readiness breakdown available." />
          ) : (
            <ul className="space-y-3">
              {ready.factors.map((f: ReadinessFactor) => {
                const pct = f.percent ?? 0;
                const color = pct >= 70 ? ACCENT : pct >= 45 ? MUTED : BAD;
                return (
                  <li key={f.factor} className="min-w-0">
                    <div className="flex items-baseline justify-between gap-2 text-xs">
                      <span className="text-slate-300 truncate">
                        {FACTOR_LABELS[f.factor] ?? f.factor}
                      </span>
                      <span className="text-slate-400 tabular-nums shrink-0">{pct}%</span>
                    </div>
                    <div className="mt-1 h-2 bg-slate-800 rounded overflow-hidden">
                      <div
                        className="h-full rounded transition-all"
                        style={{ width: `${Math.min(100, pct)}%`, background: color }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Race predictions"
          note="Garmin's estimates from current fitness. The marathon figure is extrapolated well past the longest run on record, so treat it loosely."
        >
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="text-slate-500 text-xs text-left border-b border-slate-800">
                <th className="py-2">Distance</th>
                <th className="text-right">Prediction</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["5 km", races?.time_5k_s],
                ["10 km", races?.time_10k_s],
                ["Half marathon", races?.time_half_s],
                ["Marathon", races?.time_marathon_s],
              ].map(([label, secs]) => (
                <tr key={label as string} className="border-t border-slate-800">
                  <td className="py-2 text-slate-300">{label as string}</td>
                  <td className="text-right text-slate-100">{hms(secs as number | null)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card
          title="Fitness age"
          note={
            age?.achievable != null
              ? `${round1(age.fitness)} against ${round1(age.chronological)} chronological, and ${round1(age.achievable)} achievable. Garmin computes the achievable figure at its own BMI target, which is not a realistic goal for most people — the ranking of what to work on is the useful part.`
              : "Garmin's fitness age and its components."
          }
        >
          {!age?.components.length ? (
            <Empty label="No fitness age available." />
          ) : (
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="text-slate-500 text-xs text-left border-b border-slate-800">
                  <th className="py-2">Component</th>
                  <th className="text-right">Now</th>
                  <th className="text-right">Target</th>
                  <th className="text-right">Priority</th>
                </tr>
              </thead>
              <tbody>
                {age.components.map((c) => (
                  <tr key={c.name} className="border-t border-slate-800">
                    <td className="py-2 text-slate-300">
                      {AGE_COMPONENT_LABELS[c.name] ?? c.name}
                    </td>
                    <td className="text-right text-slate-100">{round1(c.value)}</td>
                    <td className="text-right text-slate-400">
                      {c.target_value != null ? round1(c.target_value) : "—"}
                    </td>
                    <td className="text-right">
                      {c.priority === 1 ? (
                        <span className="text-red-400">1</span>
                      ) : (
                        <span className="text-slate-600">{c.priority ?? "—"}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card title="Current figures" note="The single-day numbers behind the cards above." wide>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular-nums min-w-[28rem]">
            <tbody>
              {[
                ["Training status", ts?.feedback?.replace(/_/g, " ") ?? "—"],
                [
                  "Acute / chronic load",
                  ts?.acute_load != null
                    ? `${Math.round(ts.acute_load)} / ${Math.round(ts.chronic_load ?? 0)} · ratio ${round1(ts.acwr)} ${ts.acwr_status ?? ""}`
                    : "—",
                ],
                [
                  "HRV last night",
                  hrv?.last_night != null ? `${hrv.last_night} ms (${hrv.status ?? "—"})` : "—",
                ],
                [
                  "Readiness on waking",
                  ready?.score != null
                    ? `${ready.score} ${ready.level ?? ""} · ${ready.feedback?.replace(/_/g, " ").toLowerCase() ?? ""}`
                    : "—",
                ],
                ["Sleep score last night", ready?.sleep_score ?? "—"],
                [
                  "Recovery time left",
                  ready?.latest_recovery_time_min
                    ? `${Math.round(ready.latest_recovery_time_min / 60)} h`
                    : "—",
                ],
                [
                  "Height / weight",
                  o?.profile?.height_cm
                    ? `${round1(o.profile.height_cm)} cm · ${round1(o.profile.weight_kg)} kg`
                    : "—",
                ],
              ].map(([label, value]) => (
                <tr key={label as string} className="border-t border-slate-800 first:border-t-0">
                  <td className="py-2 text-slate-400 pr-4">{label as string}</td>
                  <td className="text-slate-100">{value as string}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

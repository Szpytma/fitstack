import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { TrendingUp } from "lucide-react";
import type { DailySummary } from "@/api/types";
import { SectionCard } from "./SectionCard";

interface Props {
  data?: DailySummary[];
  loading?: boolean;
}

interface Bucket {
  date: string;
  label: string;
  steps: number;
}

/** The endpoint walks backwards from today, so the array arrives newest-first.
 *  A time axis has to read left-to-right. */
function toBuckets(rows: DailySummary[]): Bucket[] {
  return rows
    .filter((r) => r.steps != null)
    .map((r) => ({
      date: r.date,
      label: new Date(r.date + "T00:00").toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
      }),
      steps: r.steps as number,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function VolumeTrend({ data, loading }: Props) {
  const buckets = useMemo(() => toBuckets(data ?? []), [data]);

  // Every day carries the goal, but it only changes rarely — one line is enough.
  const goal = useMemo(
    () => data?.find((r) => r.step_goal != null)?.step_goal ?? null,
    [data],
  );

  const avg = useMemo(
    () =>
      buckets.length
        ? Math.round(buckets.reduce((s, b) => s + b.steps, 0) / buckets.length)
        : null,
    [buckets],
  );

  return (
    <SectionCard
      title="Daily steps · last 14 days"
      icon={<TrendingUp className="w-4 h-4 text-slate-400" />}
    >
      {loading ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : buckets.length === 0 ? (
        <div className="text-slate-500 text-sm">No daily summaries in this window.</div>
      ) : (
        <>
          <div className="flex gap-6 mb-3 text-xs">
            <div>
              <span className="text-slate-500">Average </span>
              <span className="text-slate-200 font-medium">
                {avg?.toLocaleString() ?? "—"}
              </span>
            </div>
            {goal != null && (
              <div>
                <span className="text-slate-500">Goal </span>
                <span className="text-slate-200 font-medium">{goal.toLocaleString()}</span>
              </div>
            )}
            <div>
              <span className="text-slate-500">Days on record </span>
              <span className="text-slate-200 font-medium">{buckets.length}</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={buckets} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              <XAxis dataKey="label" stroke="#64748b" fontSize={11} interval="preserveStartEnd" />
              <YAxis
                stroke="#64748b"
                fontSize={11}
                width={40}
                tickFormatter={(v) => (v >= 1000 ? `${Math.round(Number(v) / 1000)}k` : String(v))}
              />
              <Tooltip
                cursor={{ fill: "#1e293b66" }}
                contentStyle={{ background: "#0f172a", border: "1px solid #334155" }}
                formatter={(v) => [Number(v).toLocaleString(), "Steps"]}
              />
              {goal != null && (
                <ReferenceLine
                  y={goal}
                  stroke="#64748b"
                  strokeDasharray="4 4"
                  label={{
                    value: `goal ${goal.toLocaleString()}`,
                    position: "insideTopLeft",
                    fill: "#94a3b8",
                    fontSize: 10,
                  }}
                />
              )}
              <Bar dataKey="steps" fill="#059669" radius={[4, 4, 0, 0]} maxBarSize={26} name="Steps" />
            </BarChart>
          </ResponsiveContainer>
        </>
      )}
    </SectionCard>
  );
}

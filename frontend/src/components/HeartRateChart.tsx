import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { HeartPulse } from "lucide-react";
import type { HeartRatePayload } from "@/api/types";
import { SectionCard } from "./SectionCard";

interface Props {
  data?: HeartRatePayload;
  loading?: boolean;
}

interface Point {
  t: number; // minutes since local midnight — the x scale
  hr: number;
}

/** Garmin hands back `[[epoch_ms, bpm], ...]` with nulls sprinkled through the
 *  gaps where the watch was off the wrist. Those must be dropped rather than
 *  zero-filled, or the chart shows a heart rate of nothing. */
function toPoints(raw: HeartRatePayload["hr_values"]): Point[] {
  if (!raw) return [];
  const out: Point[] = [];
  for (const pair of raw) {
    const [ts, bpm] = pair;
    if (ts == null || bpm == null) continue;
    const d = new Date(ts);
    out.push({ t: d.getHours() * 60 + d.getMinutes(), hr: bpm });
  }
  return out.sort((a, b) => a.t - b.t);
}

function hhmm(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}:${String(m).padStart(2, "0")}`;
}

export function HeartRateChart({ data, loading }: Props) {
  const points = useMemo(() => toPoints(data?.hr_values ?? null), [data]);

  return (
    <SectionCard
      title="Heart rate today"
      icon={<HeartPulse className="w-4 h-4 text-slate-400" />}
    >
      {loading ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : points.length === 0 ? (
        <div className="text-slate-500 text-sm">
          No heart-rate samples for today yet — the watch syncs these in batches.
        </div>
      ) : (
        <>
          <div className="flex gap-6 mb-3 text-xs">
            <div>
              <span className="text-slate-500">Resting </span>
              <span className="text-slate-200 font-medium">{data?.resting_hr ?? "—"}</span>
            </div>
            <div>
              <span className="text-slate-500">Min </span>
              <span className="text-slate-200 font-medium">{data?.min_hr ?? "—"}</span>
            </div>
            <div>
              <span className="text-slate-500">Max </span>
              <span className="text-slate-200 font-medium">{data?.max_hr ?? "—"}</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={points} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="hrFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ef4444" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#ef4444" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                domain={[0, 1440]}
                ticks={[0, 360, 720, 1080, 1440]}
                tickFormatter={hhmm}
                stroke="#64748b"
                fontSize={11}
              />
              <YAxis domain={["auto", "auto"]} stroke="#64748b" fontSize={11} width={34} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155" }}
                labelFormatter={(v) => hhmm(Number(v))}
                formatter={(v) => [`${v} bpm`, "Heart rate"]}
              />
              {data?.resting_hr != null && (
                <ReferenceLine
                  y={data.resting_hr}
                  stroke="#64748b"
                  strokeDasharray="4 4"
                  label={{
                    value: `resting ${data.resting_hr}`,
                    position: "insideBottomLeft",
                    fill: "#94a3b8",
                    fontSize: 10,
                  }}
                />
              )}
              <Area
                type="monotone"
                dataKey="hr"
                stroke="#ef4444"
                strokeWidth={2}
                fill="url(#hrFill)"
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
                name="Heart rate"
              />
            </AreaChart>
          </ResponsiveContainer>
        </>
      )}
    </SectionCard>
  );
}

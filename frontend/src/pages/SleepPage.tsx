import { useSleepHistory } from "@/api/hooks";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Moon } from "lucide-react";

function fmtHm(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export function SleepPage() {
  const q = useSleepHistory(14);

  const chartData =
    q.data?.slice().reverse().map((s) => ({
      date: s.date.slice(5), // MM-DD
      deep: s.deep_seconds ? Math.round(s.deep_seconds / 60) : 0,
      light: s.light_seconds ? Math.round(s.light_seconds / 60) : 0,
      rem: s.rem_seconds ? Math.round(s.rem_seconds / 60) : 0,
      awake: s.awake_seconds ? Math.round(s.awake_seconds / 60) : 0,
      score: s.sleep_score,
      totalSec: s.sleep_seconds,
    })) ?? [];

  const scoreAvg =
    q.data && q.data.length
      ? Math.round(
          q.data
            .filter((s) => s.sleep_score != null)
            .reduce((a, b) => a + (b.sleep_score ?? 0), 0) /
            (q.data.filter((s) => s.sleep_score != null).length || 1),
        )
      : null;

  return (
    <div className="max-w-5xl mx-auto p-4 sm:p-6 space-y-6">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-50 flex items-center gap-2">
            <Moon className="w-5 h-5 text-slate-400" /> Sleep
          </h1>
          <p className="text-slate-400 text-sm">
            Last 14 nights
            {scoreAvg != null && ` · average score ${scoreAvg}`}
          </p>
        </div>
        {q.isFetching && <span className="text-xs text-slate-500">refreshing…</span>}
      </header>

      <section className="rounded-xl bg-slate-900 border border-slate-800 p-5">
        {q.isLoading ? (
          <div className="text-slate-500 text-sm">Loading…</div>
        ) : chartData.length === 0 ? (
          <div className="text-slate-500 text-sm">No sleep data available.</div>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="date" stroke="#64748b" />
              <YAxis stroke="#64748b" label={{ value: "minutes", angle: -90, position: "insideLeft", fill: "#64748b" }} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
              <Bar dataKey="deep" stackId="a" fill="#6366f1" name="Deep" />
              <Bar dataKey="light" stackId="a" fill="#0ea5e9" name="Light" />
              <Bar dataKey="rem" stackId="a" fill="#d946ef" name="REM" />
              <Bar dataKey="awake" stackId="a" fill="#64748b" name="Awake" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </section>

      <section className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-500 text-xs text-left border-b border-slate-800">
              <th className="py-2 px-4">Date</th>
              <th>Total</th>
              <th>Score</th>
              <th>Deep</th>
              <th>Light</th>
              <th>REM</th>
              <th>Awake</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.map((s) => (
              <tr key={s.date} className="border-t border-slate-800 hover:bg-slate-800/30">
                <td className="py-2 px-4 text-slate-300">{s.date}</td>
                <td className="text-slate-200 font-medium">{fmtHm(s.sleep_seconds)}</td>
                <td>
                  {s.sleep_score != null ? (
                    <span
                      className={
                        s.sleep_score >= 80
                          ? "text-emerald-400"
                          : s.sleep_score >= 60
                            ? "text-yellow-400"
                            : "text-red-400"
                      }
                    >
                      {s.sleep_score}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="text-slate-400">{fmtHm(s.deep_seconds)}</td>
                <td className="text-slate-400">{fmtHm(s.light_seconds)}</td>
                <td className="text-slate-400">{fmtHm(s.rem_seconds)}</td>
                <td className="text-slate-500">{fmtHm(s.awake_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

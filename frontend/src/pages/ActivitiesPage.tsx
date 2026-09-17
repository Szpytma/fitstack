import { Link } from "wouter";
import { useRecentActivities } from "@/api/hooks";
import { ChevronRight } from "lucide-react";

function fmtDuration(s: number | null): string {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
function fmtDist(m: number | null): string {
  if (m == null) return "—";
  return `${(m / 1000).toFixed(2)} km`;
}
function fmtPace(mps: number | null): string {
  if (!mps || mps <= 0) return "—";
  const secsPerKm = 1000 / mps;
  const mm = Math.floor(secsPerKm / 60);
  const ss = Math.round(secsPerKm % 60);
  return `${mm}:${ss.toString().padStart(2, "0")}/km`;
}

export function ActivitiesPage() {
  const q = useRecentActivities(50);

  return (
    <div className="max-w-6xl mx-auto p-4 sm:p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-50">Activities</h1>
        <p className="text-slate-400 text-sm">Most recent 50 · click for details</p>
      </header>

      <div className="rounded-xl bg-slate-900 border border-slate-800 divide-y divide-slate-800 overflow-hidden">
        {q.isLoading ? (
          <div className="p-4 text-slate-500 text-sm">Loading…</div>
        ) : !q.data?.length ? (
          <div className="p-4 text-slate-500 text-sm">No activities yet.</div>
        ) : (
          q.data.map((a) =>
            a.activity_id ? (
              <Link
                key={a.activity_id}
                href={`/activities/${a.activity_id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-slate-800/50 transition-colors"
              >
                <div className="min-w-0">
                  <div className="text-slate-100 font-medium truncate">
                    {a.name ?? a.type ?? "Activity"}
                  </div>
                  <div className="text-slate-500 text-xs">
                    {a.start_local ?? "—"} · {a.type ?? "—"}
                  </div>
                </div>
                <div className="flex items-center gap-6 text-xs text-slate-400 shrink-0">
                  <div className="text-right">
                    <div className="text-slate-200">{fmtDist(a.distance_m)}</div>
                    <div>{fmtDuration(a.duration_s)}</div>
                  </div>
                  <div className="text-right hidden sm:block">
                    <div className="text-slate-200">{fmtPace(a.avg_speed_mps)}</div>
                    <div>avg HR {a.avg_hr ? Math.round(a.avg_hr) : "—"}</div>
                  </div>
                  <ChevronRight className="w-4 h-4 text-slate-600" />
                </div>
              </Link>
            ) : null,
          )
        )}
      </div>
    </div>
  );
}

import type { ActivitySummary } from "@/api/types";
import { Activity } from "lucide-react";
import { Link } from "wouter";
import { SectionCard } from "./SectionCard";

interface Props {
  data?: ActivitySummary[];
  loading?: boolean;
  href?: string;
}

function fmtDuration(seconds: number | null): string {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function fmtDistance(m: number | null): string {
  if (!m) return "—";
  return `${(m / 1000).toFixed(2)} km`;
}

export function RecentActivities({ data, loading, href }: Props) {
  return (
    <SectionCard title="Recent activities" icon={<Activity className="w-4 h-4 text-slate-400" />} href={href}>
      {loading || !data ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : data.length === 0 ? (
        <div className="text-slate-500 text-sm">No activities yet.</div>
      ) : (
        <ul className="divide-y divide-slate-800">
          {data.map((a) => (
            <li key={a.activity_id ?? Math.random()}>
              {a.activity_id ? (
                <Link
                  href={`/activities/${a.activity_id}`}
                  className="py-3 flex items-center justify-between text-sm hover:bg-slate-800/40 -mx-2 px-2 rounded"
                >
                  <ActivityRow a={a} />
                </Link>
              ) : (
                <div className="py-3 flex items-center justify-between text-sm">
                  <ActivityRow a={a} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );

  function ActivityRow({ a }: { a: ActivitySummary }) {
    return (
      <>
        <div className="min-w-0">
          <div className="text-slate-100 font-medium truncate">{a.name ?? a.type ?? "Activity"}</div>
          <div className="text-slate-500 text-xs">
            {a.start_local ?? "—"} · {a.type ?? "—"}
          </div>
        </div>
        <div className="text-right text-slate-300 text-xs shrink-0 pl-4">
          <div>{fmtDuration(a.duration_s)}</div>
          <div className="text-slate-500">
            {fmtDistance(a.distance_m)} · avg HR {a.avg_hr ? Math.round(a.avg_hr) : "—"}
          </div>
        </div>
      </>
    );
  }
}

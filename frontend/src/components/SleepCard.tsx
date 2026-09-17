import type { SleepSummary } from "@/api/types";
import { Moon } from "lucide-react";
import { SectionCard } from "./SectionCard";

interface Props {
  data?: SleepSummary;
  loading?: boolean;
  href?: string;
}

function fmtHm(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export function SleepCard({ data, loading, href }: Props) {
  return (
    <SectionCard title="Sleep (last night)" icon={<Moon className="w-4 h-4 text-slate-400" />} href={href}>
      {loading || !data ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : (
        <>
          <div className="flex items-baseline gap-3">
            <div className="text-3xl font-semibold text-slate-50">
              {fmtHm(data.sleep_seconds)}
            </div>
            {data.sleep_score != null && (
              <div className="text-sm text-emerald-400 font-medium">
                Score {data.sleep_score}
              </div>
            )}
          </div>
          <div className="mt-4 grid grid-cols-4 gap-2 text-center text-xs text-slate-400">
            <Stage label="Deep" value={fmtHm(data.deep_seconds)} color="bg-indigo-500" />
            <Stage label="Light" value={fmtHm(data.light_seconds)} color="bg-sky-500" />
            <Stage label="REM" value={fmtHm(data.rem_seconds)} color="bg-fuchsia-500" />
            <Stage label="Awake" value={fmtHm(data.awake_seconds)} color="bg-slate-500" />
          </div>
        </>
      )}
    </SectionCard>
  );
}

function Stage({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div className={`h-1.5 rounded ${color} mb-1`} />
      <div className="text-slate-200 font-medium">{value}</div>
      <div>{label}</div>
    </div>
  );
}

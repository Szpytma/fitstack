import type { ReactNode } from "react";

interface Props {
  label: string;
  value: string | number;
  sub?: string;
  icon?: ReactNode;
  progress?: number; // 0..1
}

export function StatCard({ label, value, sub, icon, progress }: Props) {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 flex flex-col gap-2">
      <div className="flex items-center justify-between text-slate-400 text-sm">
        <span>{label}</span>
        {icon}
      </div>
      <div className="text-3xl font-semibold text-slate-50">{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
      {progress !== undefined && (
        <div className="mt-2 h-1.5 bg-slate-800 rounded overflow-hidden">
          <div
            className="h-full bg-emerald-500 transition-all"
            style={{ width: `${Math.min(100, Math.round(progress * 100))}%` }}
          />
        </div>
      )}
    </div>
  );
}

import { useActivityDetail } from "@/api/hooks";
import { Link } from "wouter";
import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { MapContainer, Polyline, TileLayer, useMap } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { ArrowLeft, ChevronDown, Cloud, Download, Gauge, HeartPulse, MapPin, Timer } from "lucide-react";
import "leaflet/dist/leaflet.css";
import type { ActivityDetail } from "@/api/types";
import { downloadRouteCard, type RouteCardVariant } from "@/lib/routeCard";

function fmtDuration(s: number | null | undefined): string {
  if (!s) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.round(s % 60);
  return h > 0 ? `${h}h ${m}m ${sec}s` : `${m}m ${sec}s`;
}
function fmtDist(m: number | null | undefined): string {
  if (m == null) return "—";
  return `${(m / 1000).toFixed(2)} km`;
}
function fmtPace(minPerKm: number | null | undefined): string {
  if (!minPerKm) return "—";
  const mm = Math.floor(minPerKm);
  const ss = Math.round((minPerKm - mm) * 60);
  return `${mm}:${ss.toString().padStart(2, "0")}/km`;
}
function fmtPaceMps(mps: number | null | undefined): string {
  if (!mps) return "—";
  return fmtPace((1000 / mps) / 60);
}

interface Props {
  id: number;
}

export function ActivityDetailPage({ id }: Props) {
  const q = useActivityDetail(id);

  return (
    <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-6">
      <div>
        <Link href="/activities" className="text-slate-400 hover:text-slate-200 text-sm inline-flex items-center gap-1">
          <ArrowLeft className="w-4 h-4" /> back to activities
        </Link>
      </div>

      {q.isLoading && <div className="text-slate-500 text-sm">Loading…</div>}
      {q.isError && (
        <div className="rounded-lg bg-red-950 border border-red-900 p-4 text-red-200 text-sm">
          Failed to load activity.
        </div>
      )}
      {q.data && <ActivityView data={q.data} />}
    </div>
  );
}

function ActivityView({ data }: { data: ActivityDetail }) {
  const chartData = useMemo(() => {
    const s = data.series;
    return s.time_s.map((t, i) => ({
      t: t ?? 0,
      km: s.distance_m[i] != null ? Number((s.distance_m[i]! / 1000).toFixed(2)) : null,
      hr: s.hr[i] ?? null,
      pace: s.pace_min_per_km[i] ?? null,
      alt: s.altitude_m[i] ?? null,
    }));
  }, [data.series]);

  const bounds: LatLngBoundsExpression | undefined =
    data.polyline.length >= 2
      ? data.polyline
      : undefined;

  return (
    <>
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-50">{data.name ?? "Activity"}</h1>
          <p className="text-slate-400 text-sm">
            {data.start_local ?? "—"} · {data.type ?? "—"}
          </p>
        </div>
        <ExportMenu data={data} />
      </header>

      <section className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <SummaryStat icon={<Timer className="w-4 h-4" />} label="Duration" value={fmtDuration(data.duration_s)} />
        <SummaryStat icon={<MapPin className="w-4 h-4" />} label="Distance" value={fmtDist(data.distance_m)} />
        <SummaryStat icon={<Gauge className="w-4 h-4" />} label="Avg pace" value={data.avg_pace_min_per_km ? fmtPace(data.avg_pace_min_per_km) : fmtPaceMps(data.avg_speed_mps)} />
        <SummaryStat icon={<HeartPulse className="w-4 h-4" />} label="Avg HR" value={data.avg_hr ? `${Math.round(data.avg_hr)} bpm` : "—"} sub={data.max_hr ? `max ${Math.round(data.max_hr)}` : undefined} />
        <SummaryStat icon={<Cloud className="w-4 h-4" />} label="Elev. gain" value={data.elevation_gain_m ? `${Math.round(data.elevation_gain_m)} m` : "—"} sub={data.elevation_loss_m ? `-${Math.round(data.elevation_loss_m)} m` : undefined} />
      </section>

      {bounds && (
        <section className="rounded-xl overflow-hidden border border-slate-800 h-96">
          <MapContainer bounds={bounds as LatLngBoundsExpression} className="h-full w-full">
            <TileLayer
              attribution='&copy; <a href="https://openstreetmap.org">OpenStreetMap</a>'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {/* Casing then line. Emerald vanished over parks and playing
                fields; orange has no equivalent on an OSM basemap, and the
                white casing underneath keeps it legible over any tile. */}
            <Polyline
              positions={data.polyline}
              pathOptions={{ color: "#ffffff", weight: 8, opacity: 0.9 }}
            />
            <Polyline
              positions={data.polyline}
              pathOptions={{ color: "#f97316", weight: 4 }}
            />
            <FitToBounds bounds={bounds as LatLngBoundsExpression} />
          </MapContainer>
        </section>
      )}

      {chartData.length > 0 && (
        <>
          <ChartCard title="Heart rate">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={chartData} margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="t" tickFormatter={(v) => `${Math.floor(v / 60)}m`} stroke="#64748b" />
                <YAxis domain={["auto", "auto"]} stroke="#64748b" />
                <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} labelFormatter={(v) => `${Math.floor(Number(v) / 60)}:${(Number(v) % 60).toString().padStart(2, "0")}`} />
                <Line type="monotone" dataKey="hr" stroke="#ef4444" dot={false} strokeWidth={1.5} name="HR (bpm)" />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Pace">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={chartData} margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="t" tickFormatter={(v) => `${Math.floor(v / 60)}m`} stroke="#64748b" />
                <YAxis reversed domain={["auto", "auto"]} stroke="#64748b" tickFormatter={(v) => `${Math.floor(v)}:${Math.round((Number(v) - Math.floor(v)) * 60).toString().padStart(2, "0")}`} />
                <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} formatter={(v) => (typeof v === "number" ? fmtPace(v) : String(v))} labelFormatter={(v) => `${Math.floor(Number(v) / 60)}:${(Number(v) % 60).toString().padStart(2, "0")}`} />
                <Line type="monotone" dataKey="pace" stroke="#0ea5e9" dot={false} strokeWidth={1.5} name="Pace (min/km)" />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Elevation">
            <ResponsiveContainer width="100%" height={180}>
              <AreaChart data={chartData} margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="t" tickFormatter={(v) => `${Math.floor(v / 60)}m`} stroke="#64748b" />
                <YAxis stroke="#64748b" />
                <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                <Area type="monotone" dataKey="alt" stroke="#a78bfa" fill="#a78bfa22" strokeWidth={1.5} name="Altitude (m)" />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>
        </>
      )}

      {data.hr_zones.length > 0 && (
        <ChartCard title="Time in HR zones">
          <ul className="space-y-2 text-sm">
            {data.hr_zones.map((z) => {
              const total = data.hr_zones.reduce((s, x) => s + (x.seconds ?? 0), 0);
              const pct = total > 0 ? Math.round(((z.seconds ?? 0) / total) * 100) : 0;
              return (
                <li key={z.zone ?? Math.random()} className="flex items-center gap-3">
                  <span className="w-16 text-slate-300">Zone {z.zone}</span>
                  <span className="w-20 text-slate-500 text-xs">≥{z.low_bpm} bpm</span>
                  <div className="flex-1 h-2 bg-slate-800 rounded overflow-hidden">
                    <div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="w-24 text-right text-slate-300 text-xs">{fmtDuration(z.seconds ?? null)} · {pct}%</span>
                </li>
              );
            })}
          </ul>
        </ChartCard>
      )}

      {data.splits.length > 0 && (
        <ChartCard title="Splits">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-500 text-xs text-left">
                <th className="py-2">Lap</th>
                <th>Distance</th>
                <th>Time</th>
                <th>Pace</th>
                <th>Avg HR</th>
                <th>Elev</th>
              </tr>
            </thead>
            <tbody>
              {data.splits.map((s) => (
                <tr key={s.lap ?? Math.random()} className="border-t border-slate-800">
                  <td className="py-2 text-slate-300">{s.lap}</td>
                  <td className="text-slate-300">{fmtDist(s.distance_m)}</td>
                  <td className="text-slate-300">{fmtDuration(s.duration_s)}</td>
                  <td className="text-slate-300">{fmtPaceMps(s.avg_speed_mps)}</td>
                  <td className="text-slate-300">{s.avg_hr ? Math.round(s.avg_hr) : "—"}</td>
                  <td className="text-slate-500">{s.elevation_gain_m ? `+${Math.round(s.elevation_gain_m)}m` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ChartCard>
      )}

      {data.weather.conditions && (
        <ChartCard title="Weather">
          <div className="text-sm text-slate-300 flex gap-6 flex-wrap">
            <span>{data.weather.conditions}</span>
            {data.weather.temp_c != null && <span>{Math.round(data.weather.temp_c)}°C</span>}
            {data.weather.apparent_c != null && <span>feels {Math.round(data.weather.apparent_c)}°C</span>}
            {data.weather.humidity != null && <span>humidity {Math.round(data.weather.humidity)}%</span>}
            {data.weather.wind_kph != null && <span>wind {Math.round(data.weather.wind_kph)} kph</span>}
          </div>
        </ChartCard>
      )}
    </>
  );
}

const EXPORTS: { variant: RouteCardVariant; label: string; hint: string }[] = [
  { variant: "full", label: "Route + details", hint: "Title, map and stats" },
  { variant: "text", label: "Details only", hint: "Title and stats, no map" },
  { variant: "map", label: "Route only", hint: "Just the map line" },
];

/** Export picker. All three variants render on a transparent background, so
 *  they can be layered over a photo. */
function ExportMenu({ data }: { data: ActivityDetail }) {
  const [open, setOpen] = useState(false);
  const hasRoute = data.polyline.length >= 2;

  // Without GPS only the text card is possible; offering the others would hand
  // back an empty PNG.
  const options = hasRoute ? EXPORTS : EXPORTS.filter((e) => e.variant === "text");

  return (
    <div className="relative shrink-0">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        title="Download as PNG"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-white text-sm"
      >
        <Download className="w-4 h-4" /> PNG
        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <>
          {/* Click-away layer so the menu closes without a document listener. */}
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            role="menu"
            className="absolute right-0 mt-1 z-40 w-56 rounded-lg border border-slate-700 bg-slate-900 shadow-xl overflow-hidden"
          >
            {options.map(({ variant, label, hint }) => (
              <button
                key={variant}
                role="menuitem"
                onClick={() => {
                  downloadRouteCard(data, variant);
                  setOpen(false);
                }}
                className="w-full text-left px-3 py-2 hover:bg-slate-800 border-b border-slate-800 last:border-0"
              >
                <div className="text-sm text-slate-100">{label}</div>
                <div className="text-[11px] text-slate-500">{hint}</div>
              </button>
            ))}
            <div className="px-3 py-1.5 text-[10px] text-slate-600 bg-slate-950/60">
              Transparent background
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function SummaryStat({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-4">
      <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
        <span>{label}</span>
        {icon}
      </div>
      <div className="text-xl font-semibold text-slate-50">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl bg-slate-900 border border-slate-800 p-5">
      <h2 className="text-slate-200 font-semibold mb-3">{title}</h2>
      {children}
    </section>
  );
}

function FitToBounds({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap();
  if (bounds) map.fitBounds(bounds, { padding: [20, 20] });
  return null;
}

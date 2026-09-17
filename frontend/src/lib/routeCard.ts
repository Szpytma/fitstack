import type { ActivityDetail } from "@/api/types";

/**
 * Renders an activity as a shareable PNG: the route line on a plain card with
 * the headline stats, in the style of a Strava share image.
 *
 * Deliberately tile-free. Drawing map tiles would mean external requests at
 * export time, OSM attribution and rate-limit obligations, and a canvas that
 * silently taints (and so refuses toDataURL) if any tile lacks CORS headers.
 * A route on a clean background always works, offline included.
 */

export type RouteCardVariant = "full" | "text" | "map";

const CARD_W = 1200;
const PAD = 80;

/** Each variant gets its own height rather than a fixed canvas with holes in
 *  it — a text-only card padded to 1500px would export mostly empty pixels. */
const LAYOUT: Record<
  RouteCardVariant,
  { height: number; header: boolean; route: boolean; stats: boolean; suffix: string }
> = {
  full: { height: 1500, header: true, route: true, stats: true, suffix: "" },
  text: { height: 620, header: true, route: false, stats: true, suffix: "-stats" },
  map: { height: 1200, header: false, route: true, stats: false, suffix: "-route" },
};

// Everything is white because the card is transparent and lands on whoever's
// photo — a mid-tone colour would disappear against foliage or sky. Legibility
// comes from a soft dark shadow under every mark instead of from a background.
// Solid white throughout. Opacity was the wrong lever for hierarchy on a
// transparent card — it reads as washed out over a photo. Size and weight carry
// the hierarchy instead, and every mark stays fully opaque.
const INK = "#ffffff";
const ROUTE = "#ffffff";
const START = "#4ade80";
const END = "#fb7185";

const FONT = "system-ui, -apple-system, Segoe UI, Roboto, sans-serif";

/**
 * Drop shadow that keeps white marks readable on a light background.
 *
 * Two passes: a tight, near-opaque shadow for edge definition, then a wide
 * diffuse one that darkens the photo behind the mark. One pass alone either
 * looks like a hard outline or fails to lift the text off a bright sky.
 */
function withShadow(ctx: CanvasRenderingContext2D, draw: () => void) {
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.45)";
  ctx.shadowBlur = 34;
  ctx.shadowOffsetY = 4;
  draw();
  ctx.shadowColor = "rgba(0,0,0,0.55)";
  ctx.shadowBlur = 8;
  ctx.shadowOffsetY = 1;
  draw();
  ctx.restore();
}

/** `letterSpacing` is well supported in Chrome but not universal. */
function setTracking(ctx: CanvasRenderingContext2D, px: string) {
  if ("letterSpacing" in ctx) {
    (ctx as CanvasRenderingContext2D & { letterSpacing: string }).letterSpacing = px;
  }
}

function fmtDuration(s: number | null | undefined): string {
  if (!s) return "—";
  const t = Math.round(s);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  return h
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
}

function fmtPace(minPerKm: number | null | undefined): string {
  if (!minPerKm || minPerKm <= 0) return "—";
  const m = Math.floor(minPerKm);
  const s = Math.round((minPerKm - m) * 60);
  // 7.99 min/km must read 8:00, not 7:60.
  return s === 60 ? `${m + 1}:00/km` : `${m}:${String(s).padStart(2, "0")}/km`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.replace(" ", "T"));
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }) + " · " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/**
 * Project lat/lon into card space.
 *
 * Web Mercator's y term matters even over a few km: at 51°N a degree of
 * longitude is ~0.63 of a degree of latitude, so plotting raw degrees would
 * squash the route horizontally. One scale factor is used for both axes so the
 * shape stays true rather than being stretched to fill the box.
 */
function project(
  points: number[][],
  box: { x: number; y: number; w: number; h: number },
): { x: number; y: number }[] {
  const rad = (deg: number) => (deg * Math.PI) / 180;
  // Both axes must be in the same units or the aspect ratio is nonsense:
  // Mercator y is radians, so longitude has to be radians too, not degrees.
  const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + rad(lat) / 2));

  const xs = points.map((p) => rad(p[1]));
  const ys = points.map((p) => mercY(p[0]));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  const spanX = maxX - minX || 1e-6;
  const spanY = maxY - minY || 1e-6;
  const scale = Math.min(box.w / spanX, box.h / spanY);

  // Centre whichever axis has slack.
  const offX = box.x + (box.w - spanX * scale) / 2;
  const offY = box.y + (box.h - spanY * scale) / 2;

  return points.map((p) => ({
    x: offX + (rad(p[1]) - minX) * scale,
    // Canvas y grows downward; Mercator y grows north.
    y: offY + (maxY - mercY(p[0])) * scale,
  }));
}

export interface RouteCardResult {
  canvas: HTMLCanvasElement;
  filename: string;
}

export function renderRouteCard(
  a: ActivityDetail,
  variant: RouteCardVariant = "full",
): RouteCardResult | null {
  const layout = LAYOUT[variant];
  const CARD_H = layout.height;

  const points = (a.polyline ?? []).filter(
    (p) => Array.isArray(p) && p.length >= 2 && p[0] != null && p[1] != null,
  );
  // Only the variants that actually draw the route need GPS.
  if (layout.route && points.length < 2) return null;

  const canvas = document.createElement("canvas");
  canvas.width = CARD_W;
  canvas.height = CARD_H;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  // No background fill: the canvas stays transparent so the PNG can be dropped
  // straight onto a photo, the way Strava's story overlay works.
  ctx.textBaseline = "top";

  // --- header ---
  if (layout.header) {
    withShadow(ctx, () => {
      ctx.fillStyle = INK;
      ctx.font = `700 78px ${FONT}`;
      setTracking(ctx, "-2px"); // large type needs pulling in, not spacing out
      const title = a.name ?? "Activity";
      ctx.fillText(title.length > 24 ? `${title.slice(0, 23)}…` : title, PAD, PAD);

      ctx.font = `600 28px ${FONT}`;
      setTracking(ctx, "3px");
      ctx.fillText(fmtDate(a.start_local).toUpperCase(), PAD, PAD + 100);
      setTracking(ctx, "0px");
    });
  }

  // --- route ---
  if (layout.route) {
    // In "full" the route sits between header and stats; alone it gets the
    // whole canvas so the trace is as large as the format allows.
    const mapBox = layout.header
      ? { x: PAD, y: 280, w: CARD_W - PAD * 2, h: 800 }
      : { x: PAD, y: PAD, w: CARD_W - PAD * 2, h: CARD_H - PAD * 2 };
    const pts = project(points, mapBox);

    ctx.lineJoin = "round";
    ctx.lineCap = "round";

    const trace = () => {
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      ctx.stroke();
    };

    // One stroke, one shadow. Drawing a dark under-stroke would show through the
    // transparent background as a grey halo.
    withShadow(ctx, () => {
      ctx.strokeStyle = ROUTE;
      ctx.lineWidth = 14;
      trace();
    });

    const dot = (p: { x: number; y: number }, color: string) => {
      withShadow(ctx, () => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 17, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      });
      // A white ring separates the marker from the route without needing a
      // background-coloured hole punched behind it.
      ctx.beginPath();
      ctx.arc(p.x, p.y, 17, 0, Math.PI * 2);
      ctx.strokeStyle = INK;
      ctx.lineWidth = 6;
      ctx.stroke();
    };
    dot(pts[0], START);
    dot(pts[pts.length - 1], END);
  }

  // --- stats ---
  const stats: [string, string][] = [
    ["Distance", a.distance_m ? `${(a.distance_m / 1000).toFixed(2)} km` : "—"],
    ["Time", fmtDuration(a.duration_s)],
    ["Avg pace", fmtPace(a.avg_pace_min_per_km)],
    ["Avg HR", a.avg_hr ? `${Math.round(a.avg_hr)} bpm` : "—"],
    ["Elevation", a.elevation_gain_m != null ? `${Math.round(a.elevation_gain_m)} m` : "—"],
    ["Calories", a.calories_kcal ? `${Math.round(a.calories_kcal)}` : "—"],
  ];

  if (layout.stats) {
    const cols = 3;
    const cellW = (CARD_W - PAD * 2) / cols;
    // Below the route in "full"; straight under the header when text-only.
    const statsTop = layout.route ? 1150 : 300;

    withShadow(ctx, () => {
      ctx.fillStyle = INK;
      stats.forEach(([label, value], i) => {
        const cx = PAD + (i % cols) * cellW;
        const cy = statsTop + Math.floor(i / cols) * 132;

        ctx.font = `700 24px ${FONT}`;
        setTracking(ctx, "3px");
        ctx.fillText(label.toUpperCase(), cx, cy);

        ctx.font = `700 66px ${FONT}`;
        setTracking(ctx, "-1px");
        ctx.fillText(value, cx, cy + 34);
      });
      setTracking(ctx, "0px");
    });
  }

  const slug = (a.name ?? "activity")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const day = (a.start_local ?? "").slice(0, 10) || "route";

  return { canvas, filename: `${slug || "activity"}-${day}${layout.suffix}.png` };
}

export function downloadRouteCard(
  a: ActivityDetail,
  variant: RouteCardVariant = "full",
): boolean {
  const result = renderRouteCard(a, variant);
  if (!result) return false;
  const url = result.canvas.toDataURL("image/png");
  const link = document.createElement("a");
  link.href = url;
  link.download = result.filename;
  link.click();
  return true;
}

/**
 * Chart palette + formatting helpers.
 *
 * Colours are the validated data-viz reference palette. The pairs that ever
 * co-occur in one chart (blue+orange for p50/p95, blue+red for low/high risk)
 * pass the CVD and normal-vision separation gates in both light and dark modes.
 * We read the resolved value from CSS custom properties so a single set of
 * tokens drives both the chart marks and the surrounding UI.
 */

export type SeriesRole = "blue" | "orange" | "red" | "green";

// Fallbacks mirror the CSS token values (light mode); the live value is read
// from CSS at runtime so light/dark stay in sync with index.css.
const FALLBACK: Record<string, string> = {
  "--series-blue": "#2a78d6",
  "--series-orange": "#eb6834",
  "--series-red": "#e34948",
  "--series-green": "#0ca30c",
  "--surface": "#fcfcfb",
  "--grid": "#e1e0d9",
  "--axis": "#c3c2b7",
  "--text-primary": "#0b0b0b",
  "--text-secondary": "#52514e",
  "--text-muted": "#898781",
};

export function cssVar(name: string): string {
  if (typeof window === "undefined") return FALLBACK[name] ?? "#000";
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || FALLBACK[name] || "#000";
}

// --- number / time formatting ------------------------------------------------

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const grouped = new Intl.NumberFormat("en-US");

export function fmtCompact(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return compact.format(n);
}

export function fmtInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return grouped.format(Math.round(n));
}

export function fmtMs(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const digits = n < 10 ? 2 : n < 100 ? 1 : 0;
  return `${n.toFixed(digits)} ms`;
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const digits = n === 0 || n >= 10 ? (Number.isInteger(n) ? 0 : 1) : 2;
  return `${n.toFixed(digits)}%`;
}

/** Parse the ISO-ish timestamps the statement API returns (UTC, "...Z"). */
function parseTs(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T"));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Axis tick for a time bucket, resolution-aware. */
export function fmtBucketTick(iso: string, unit: string): string {
  const d = parseTs(iso);
  if (!d) return iso;
  if (unit === "DAY" || unit === "WEEK" || unit === "MONTH") {
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }
  if (unit === "HOUR") {
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  if (unit === "SECOND") {
    return d.toLocaleTimeString([], { minute: "2-digit", second: "2-digit" });
  }
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Full timestamp for tooltips / table rows. */
export function fmtBucketFull(iso: string): string {
  const d = parseTs(iso);
  if (!d) return iso;
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

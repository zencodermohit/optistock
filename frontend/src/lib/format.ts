/**
 * Number, currency and date formatting — in one place, on purpose.
 *
 * Formatting scattered across screens is how a dashboard ends up showing
 * "₹4,82,00,000", "48200000" and "4.82Cr" for the same figure on three
 * different pages. Every number the user sees goes through this file.
 *
 * The data is Indian-market, so currency uses the lakh/crore grouping people
 * there actually read.
 */

const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const INR_PRECISE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const COUNT = new Intl.NumberFormat("en-IN");

/** Full rupee amount, e.g. "₹72,999". Use in tables and detail views. */
export function currency(value: number | string | null | undefined): string {
  const n = toNumber(value);
  return n === null ? "—" : INR.format(n);
}

/** Two decimal places, for unit prices and line totals. */
export function currencyPrecise(value: number | string | null | undefined): string {
  const n = toNumber(value);
  return n === null ? "—" : INR_PRECISE.format(n);
}

/**
 * Abbreviated for headline metrics, e.g. "₹4.82 Cr".
 *
 * A KPI tile has room for six characters, not twelve — "₹48,20,00,000" either
 * wraps or shrinks the tile. The precise figure belongs in a tooltip.
 */
export function currencyCompact(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";

  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  if (abs >= 1e3) return `₹${(n / 1e3).toFixed(1)}k`;
  return INR.format(n);
}

/** Thousands-separated integer, e.g. "18,561". */
export function count(value: number | string | null | undefined): string {
  const n = toNumber(value);
  return n === null ? "—" : COUNT.format(n);
}

/** Signed percentage for deltas, e.g. "+12.4%". */
export function percentDelta(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

/** Plain percentage, e.g. "88.2%". */
export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

/** "8 Aug 2026" */
export function date(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d
    ? d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    : "—";
}

/** "8 Aug, 14:32" — for event streams and audit rows. */
export function dateTime(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d
    ? d.toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
}

/**
 * "3 minutes ago". Live feeds read far better in relative time — an absolute
 * timestamp makes you do arithmetic to answer "is this recent?".
 */
export function relativeTime(value: string | Date | null | undefined): string {
  const d = toDate(value);
  if (!d) return "—";

  const seconds = Math.round((Date.now() - d.getTime()) / 1000);
  if (seconds < 45) return "just now";

  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31536000],
    ["month", 2592000],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, secondsPerUnit] of units) {
    if (seconds >= secondsPerUnit) {
      return rtf.format(-Math.floor(seconds / secondsPerUnit), unit);
    }
  }
  return "just now";
}

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

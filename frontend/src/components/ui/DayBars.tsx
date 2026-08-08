import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A day-by-day bar series.
 *
 * Bars rather than a line: these are discrete daily totals, and a line drawn
 * between them implies a continuous quantity that was never measured. Bars in
 * HTML rather than SVG, because a bar is a rectangle and the browser lays
 * rectangles out responsively without any viewBox arithmetic -- and the corner
 * radius stays 4px at every width instead of scaling with the drawing.
 *
 * One series per chart, always. Two measures on two y-scales in one frame is
 * the single most misleading thing a dashboard can do: the crossing point where
 * one line "overtakes" the other is an artefact of the two scales chosen, and
 * it moves if either is changed. Two measures means two charts.
 */

export interface DayPoint {
  date: string;
  value: number;
}

export function DayBars({
  points,
  label,
  format,
  tone = "accent",
  height = "h-32",
  showAxis = true,
}: {
  points: DayPoint[];
  /** Names the series. A single-series chart needs this, not a legend box. */
  label: string;
  format: (value: number) => string;
  tone?: "accent" | "muted";
  height?: string;
  showAxis?: boolean;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);

  const max = Math.max(...points.map((p) => p.value), 1);
  const peak = points.reduce(
    (best, p, i) => (p.value > points[best].value ? i : best),
    0,
  );

  if (asTable) {
    return (
      <figure>
        <Caption label={label} max={max} format={format} onToggle={() => setAsTable(false)} showing="table" />
        <div className="max-h-48 overflow-y-auto rounded-sm border border-border">
          <table className="w-full text-sm">
            <tbody className="zebra">
              {points.map((p) => (
                <tr key={p.date}>
                  <td className="px-3 py-1 font-mono text-2xs text-ink-muted">
                    {shortDate(p.date)}
                  </td>
                  <td className="tnum px-3 py-1 text-right">{format(p.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </figure>
    );
  }

  return (
    <figure>
      <Caption label={label} max={max} format={format} onToggle={() => setAsTable(true)} showing="chart" />

      <div className="relative">
        {/* Recessive gridlines. They exist to let the eye estimate a height,
            not to be looked at. */}
        <div className={cn("pointer-events-none absolute inset-x-0", height)} aria-hidden>
          <div className="absolute inset-x-0 top-0 border-t border-border" />
          <div className="absolute inset-x-0 top-1/2 border-t border-border/60" />
        </div>

        <div className={cn("flex items-end gap-[2px]", height)}>
          {points.map((point, index) => (
            <button
              key={point.date}
              type="button"
              className="group relative flex h-full flex-1 items-end focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(index)}
              onBlur={() => setHovered(null)}
              // Every bar is reachable and readable on its own, which is what
              // makes the chart usable without seeing it.
              aria-label={`${shortDate(point.date)}: ${format(point.value)}`}
            >
              <span
                className={cn(
                  // Capped and centred. Marks stay thin at any container width
                  // instead of turning into slabs when the window is wide.
                  "mx-auto w-full max-w-[14px] rounded-t-[4px] transition-colors",
                  tone === "accent" ? "bg-accent" : "bg-ink-subtle",
                  hovered === index && "bg-accent-hover",
                  point.value === 0 && "bg-border-strong",
                )}
                style={{
                  // A floor of 2px so a zero day is visibly a day with nothing
                  // in it, rather than a gap the eye reads as missing data.
                  height: `${Math.max((point.value / max) * 100, point.value > 0 ? 2 : 1)}%`,
                }}
              />
            </button>
          ))}
        </div>

        {hovered !== null && (
          <div
            className="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 -translate-y-full rounded-sm border border-border-strong bg-surface px-2 py-1 shadow-md"
            style={{ left: `${((hovered + 0.5) / points.length) * 100}%` }}
            role="status"
          >
            <p className="font-mono text-2xs whitespace-nowrap text-ink-subtle">
              {shortDate(points[hovered].date)}
            </p>
            <p className="tnum text-sm whitespace-nowrap">
              {format(points[hovered].value)}
            </p>
          </div>
        )}
      </div>

      {showAxis && (
        <div className="mt-1.5 flex justify-between font-mono text-2xs text-ink-subtle">
          <span>{shortDate(points[0]?.date)}</span>
          {/* One direct label, on the peak. A number over every bar is noise;
              the highest point is the one worth naming. */}
          <span className="text-ink-muted">
            peak {format(points[peak]?.value ?? 0)}
          </span>
          <span>{shortDate(points[points.length - 1]?.date)}</span>
        </div>
      )}
    </figure>
  );
}

function Caption({
  label,
  max,
  format,
  onToggle,
  showing,
}: {
  label: string;
  max: number;
  format: (value: number) => string;
  onToggle: () => void;
  showing: "chart" | "table";
}) {
  return (
    <figcaption className="mb-2 flex items-baseline justify-between gap-3">
      <span className="eyebrow">{label}</span>
      <span className="flex items-baseline gap-3">
        <span className="font-mono text-2xs text-ink-subtle">
          max {format(max)}
        </span>
        <button
          type="button"
          onClick={onToggle}
          className="font-mono text-2xs text-accent underline-offset-2 hover:underline"
        >
          {showing === "chart" ? "table" : "chart"}
        </button>
      </span>
    </figcaption>
  );
}

function shortDate(iso: string | undefined): string {
  if (!iso) return "";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}

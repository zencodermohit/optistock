import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * The trace: one stock line's recent history, drawn at row height.
 *
 * This is the thing the table is for. A quantity tells you where a line is; the
 * trace tells you where it is going, and a line converging on its reorder rule
 * is visible days before any alert fires. Three hundred rows become three
 * hundred readable stories instead of three hundred numbers.
 *
 * Hand-drawn SVG rather than a chart library: at 68x18 with no axes, ticks,
 * legend or tooltip, every feature a charting library offers is weight we would
 * ship and then switch off.
 */

interface TraceProps {
  /** Oldest to newest. Fewer than two points cannot make a line. */
  points: number[] | undefined;
  /** Drawn as a dashed rule across the trace. Omitted when not configured. */
  reorderPoint?: number;
  /** True when the line currently sits at or below its reorder point. */
  low?: boolean;
  className?: string;
  /** Describes the trace for screen readers, which cannot see a polyline. */
  label?: string;
}

const W = 68;
const H = 18;
const PAD = 1.5;

export function Trace({
  points,
  reorderPoint,
  low = false,
  className,
  label,
}: TraceProps) {
  // useId keeps the clip path unique. Three hundred rows each defining "#fade"
  // means three hundred elements pointing at whichever one rendered last.
  const clipId = useId();

  if (!points || points.length < 2) {
    return (
      <span
        className={cn("inline-block text-2xs text-ink-subtle", className)}
        style={{ width: W }}
        aria-hidden
      >
        &nbsp;
      </span>
    );
  }

  // Scale to the data, not to zero. A line that sits between 800 and 900 units
  // is flat against a zero baseline, and flat is exactly the information we are
  // trying not to lose. The reorder point joins the extent so the rule is
  // always on screen.
  const candidates = [...points];
  if (reorderPoint && reorderPoint > 0) candidates.push(reorderPoint);
  const min = Math.min(...candidates);
  const max = Math.max(...candidates);
  const span = max - min || 1;

  const x = (i: number) => PAD + (i / (points.length - 1)) * (W - PAD * 2);
  const y = (v: number) => H - PAD - ((v - min) / span) * (H - PAD * 2);

  const line = points.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${PAD},${H} ${line} ${W - PAD},${H}`;

  const stroke = low ? "var(--color-warning)" : "var(--color-ink-muted)";
  const last = points[points.length - 1];

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      className={cn("block overflow-visible", className)}
      role="img"
      aria-label={
        label ??
        `Recent movement, now ${last.toLocaleString()} units${
          low ? ", at or below reorder point" : ""
        }`
      }
    >
      <defs>
        {/* The oldest days fade out: the trace should read left-to-right as
            "then, and now", with now carrying the weight. */}
        <linearGradient id={clipId} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.04" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0.16" />
        </linearGradient>
      </defs>

      <polygon points={area} fill={`url(#${clipId})`} />

      {/* The reorder rule is a reference mark, not an alarm, so it stays
          neutral on every row — an amber rule under three hundred healthy
          traces is three hundred false alarms. Dashed, so a line crossing
          below it reads as a shape and not only as a colour change: the trace
          has to work for someone who cannot separate amber from grey. */}
      {reorderPoint && reorderPoint > 0 ? (
        <line
          x1={0}
          x2={W}
          y1={y(reorderPoint)}
          y2={y(reorderPoint)}
          stroke="var(--color-ink-subtle)"
          strokeWidth="1"
          strokeDasharray="3 2"
          opacity="0.55"
        />
      ) : null}

      <polyline
        points={line}
        fill="none"
        stroke={stroke}
        strokeWidth="1.25"
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {/* The head of the line, so the eye lands on today rather than on the
          middle of the series. */}
      <circle cx={x(points.length - 1)} cy={y(last)} r="1.75" fill={stroke} />
    </svg>
  );
}

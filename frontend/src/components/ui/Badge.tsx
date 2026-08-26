import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badge = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 " +
    "font-display text-2xs font-bold tracking-wide whitespace-nowrap uppercase",
  {
    variants: {
      tone: {
        neutral: "border-border-strong bg-sunken text-ink-muted",
        accent: "border-accent bg-accent text-on-accent",
        outline: "border-accent-border bg-accent-soft text-accent-hover",
        success: "border-success/25 bg-success-soft text-success",
        warning: "border-warning/25 bg-warning-soft text-warning",
        danger: "border-danger/25 bg-danger-soft text-danger",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badge> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}

/**
 * ABC class is an ordinal scale, not three categories, so it is encoded by
 * weight rather than by hue: A is solid, B is outlined, C is bare. Giving each
 * class its own colour would imply they are unrelated kinds of thing, and would
 * spend three hues on a scale that only ever runs one direction.
 *
 * Defined once so the product table and the Pareto chart can never disagree
 * about what "A" looks like.
 */
export function AbcBadge({ value }: { value: string | null | undefined }) {
  if (!value) {
    return <span className="font-mono text-2xs text-ink-subtle">—</span>;
  }

  const tone = ({ A: "accent", B: "outline", C: "neutral" } as const)[
    value as "A" | "B" | "C"
  ];

  return (
    <Badge tone={tone ?? "neutral"} className="w-5 justify-center px-0">
      {value}
    </Badge>
  );
}

/** Product and order lifecycle state. */
export function StatusBadge({ value }: { value: string }) {
  const tone =
    (
      {
        active: "success",
        completed: "success",
        delivered: "success",
        draft: "neutral",
        pending: "warning",
        archived: "neutral",
        discontinued: "danger",
        cancelled: "danger",
        rejected: "danger",
      } as const
    )[value] ?? "neutral";

  return <Badge tone={tone}>{value}</Badge>;
}

/**
 * Stock health, and the one place warning/danger are allowed to appear on a
 * quantity. Healthy is deliberately unmarked — you don't stamp "FINE" on a
 * report, you stamp the problems, and a column of green ticks is a column the
 * eye has to filter before it can find the two rows that matter.
 */
export function StockMark({
  quantity,
  reorderPoint,
}: {
  quantity: number;
  reorderPoint: number;
}) {
  if (quantity <= 0) return <Badge tone="danger">Out</Badge>;
  // A reorder point of 0 means "not configured", so it never reads as low.
  if (reorderPoint > 0 && quantity <= reorderPoint)
    return <Badge tone="warning">Low</Badge>;
  return null;
}

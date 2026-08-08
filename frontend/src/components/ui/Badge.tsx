import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badge = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 " +
    "text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "border-border-strong bg-sunken text-ink-muted",
        accent: "border-accent-border bg-accent-soft text-accent-hover",
        success: "border-success/20 bg-success-soft text-success",
        warning: "border-warning/20 bg-warning-soft text-warning",
        danger: "border-danger/20 bg-danger-soft text-danger",
        info: "border-info/20 bg-info-soft text-info",
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
 * ABC class carries meaning, so it gets a consistent colour everywhere it
 * appears — A is where the revenue is, C is the long tail. Defining it once
 * stops the product table and the Pareto chart disagreeing about what "A" looks
 * like.
 */
export function AbcBadge({ value }: { value: string | null | undefined }) {
  if (!value) {
    return <span className="text-xs text-ink-subtle">—</span>;
  }
  const tone = { A: "accent", B: "info", C: "neutral" }[value] as
    | "accent"
    | "info"
    | "neutral"
    | undefined;

  return (
    <Badge tone={tone ?? "neutral"} className="w-6 justify-center px-0">
      {value}
    </Badge>
  );
}

/** Product lifecycle state. */
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

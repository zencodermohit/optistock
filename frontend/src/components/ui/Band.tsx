import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A panel — the surface everything else sits on.
 *
 * Named Band from the era when this was a printed report and separation came
 * from tint alone. It now lifts: a soft wide shadow and a generous radius, so a
 * panel reads as an object on a floor rather than ink on paper. The name stays
 * because sixteen screens compose it, and renaming a working primitive to match
 * a stylesheet is churn, not design.
 *
 * Elevation is one step only. Twelve panels each claiming a different height
 * is how a dashboard turns into twelve competing planes — the thing the old
 * no-shadow rule was protecting against. The answer is a single honest step,
 * not zero.
 */
export function Band({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-border bg-surface shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export function BandHeader({
  label,
  title,
  description,
  action,
  className,
}: {
  /** Mono, uppercase, stamped at the head of the band. Say what this is. */
  label?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  /** Right-aligned control: a filter, a link, a menu. */
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 " +
          "border-b border-border px-4 py-3",
        className,
      )}
    >
      <div className="min-w-0">
        {label && <p className="eyebrow">{label}</p>}
        {title && (
          <h3 className="mt-0.5 text-lg leading-tight font-semibold">{title}</h3>
        )}
        {description && (
          <p className="mt-1 text-sm text-ink-muted">{description}</p>
        )}
      </div>
      {/* Controls take the full width on a narrow screen and wrap onto their
          own line. Left to shrink instead, they slide under the band's clipped
          edge and the search box loses its right half. */}
      {action && (
        <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
          {action}
        </div>
      )}
    </div>
  );
}

export function BandBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...props} />;
}

export function BandFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "border-t border-border bg-sunken/60 px-4 py-2 text-xs text-ink-muted",
        className,
      )}
      {...props}
    />
  );
}

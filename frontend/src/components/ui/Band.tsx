import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A band is a section of the report.
 *
 * It replaces the floating card: hairline border, tinted header, no shadow.
 * Paper does not cast a shadow on paper, so separation comes from tint and rule
 * alone. That constraint is what stops twelve panels on a dashboard turning
 * into twelve competing planes.
 */
export function Band({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-surface",
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
          "border-b border-border bg-sunken px-4 py-2.5",
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

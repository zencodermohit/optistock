/**
 * Loading, empty and error states.
 *
 * These decide whether an app feels finished. A blank screen while data loads,
 * a bare "No results", or a raw stack trace on failure are the three fastest
 * ways to look unfinished — and they are the three states a demo hits most,
 * because demos run on cold caches and flaky wifi.
 *
 * Rules used here:
 *   Loading — mimic the SHAPE of what is coming, so the layout doesn't jump.
 *   Empty   — say why it is empty and what to do next. Never just "No data".
 *   Error   — say what failed, in plain words, and offer the way out.
 */

import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* Loading                                                                     */
/* -------------------------------------------------------------------------- */

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md bg-sunken shimmer",
        className,
      )}
      aria-hidden
    />
  );
}

/** Placeholder rows shaped like the table that is loading. */
export function TableSkeleton({ rows = 8, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="divide-y divide-border" aria-busy aria-label="Loading">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-4 px-5 py-3">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton
              key={c}
              className={cn(
                "h-4",
                c === 0 ? "w-1/4" : c === cols - 1 ? "ml-auto w-16" : "w-1/6",
              )}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Placeholder for a KPI tile. */
export function MetricSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-surface p-5 shadow-xs">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-3 h-8 w-32" />
      <Skeleton className="mt-3 h-3 w-20" />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty                                                                       */
/* -------------------------------------------------------------------------- */

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  /** Why is it empty, and what would fill it? */
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-6 py-16 text-center",
        className,
      )}
    >
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-sunken text-ink-subtle">
        {icon ?? <Inbox className="h-5 w-5" />}
      </div>
      <h3 className="text-lg font-semibold">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm text-ink-muted">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Error                                                                       */
/* -------------------------------------------------------------------------- */

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const { title, message, retryable } = describe(error);

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-6 py-16 text-center",
        className,
      )}
      role="alert"
    >
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-danger-soft text-danger">
        <AlertTriangle className="h-5 w-5" />
      </div>
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-1.5 max-w-md text-sm text-ink-muted">{message}</p>
      {onRetry && retryable && (
        <Button
          variant="secondary"
          size="sm"
          className="mt-5"
          onClick={onRetry}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
        >
          Try again
        </Button>
      )}
    </div>
  );
}

/** Turn a thrown value into something worth showing a person. */
function describe(error: unknown): {
  title: string;
  message: string;
  retryable: boolean;
} {
  if (error instanceof ApiError) {
    if (error.status === 0)
      return {
        title: "Can't reach the server",
        message:
          "The API isn't responding. Check that the backend is running, then try again.",
        retryable: true,
      };
    if (error.status === 403)
      return {
        title: "Not allowed",
        message: "Your role doesn't have permission to view this.",
        retryable: false,
      };
    if (error.status === 404)
      return {
        title: "Not found",
        message: "This doesn't exist, or it belongs to another organisation.",
        retryable: false,
      };
    if (error.status >= 500)
      return {
        title: "Something went wrong",
        message: "The server hit an error. This is usually temporary.",
        retryable: true,
      };
    return { title: "That didn't work", message: error.message, retryable: false };
  }

  return {
    title: "Something went wrong",
    message: error instanceof Error ? error.message : "An unexpected error occurred.",
    retryable: true,
  };
}

import type { HTMLAttributes, ThHTMLAttributes, TdHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * Table primitives.
 *
 * Three decisions worth knowing:
 *  - Rows are banded, not ruled. Greenbar paper alternated tint so the eye
 *    could follow one row across a wide sheet without a straightedge; doing
 *    both bands and hairlines would be two devices solving one problem.
 *  - `numeric` right-aligns and switches to tabular figures. Numbers compare by
 *    their right edge, so left-aligned currency in a column is genuinely harder
 *    to scan.
 *  - The header is sticky, because an inventory table is 300 rows long and a
 *    column heading you have scrolled past is a column heading you don't have.
 */

export function TableWrap({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("overflow-auto", className)} {...props} />;
}

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <table
      className={cn("w-full border-collapse text-sm", className)}
      {...props}
    />
  );
}

export function THead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      // Opaque, not translucent: banded rows scrolling under a see-through
      // header turn the column labels into a flicker.
      className={cn("sticky top-0 z-10 bg-canvas", className)}
      {...props}
    />
  );
}

export function TBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("zebra", className)} {...props} />;
}

export function TR({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("transition-colors", className)} {...props} />;
}

interface CellProps {
  /** Right-align and use tabular figures. */
  numeric?: boolean;
}

export function TH({
  className,
  numeric,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement> & CellProps) {
  return (
    <th
      scope="col"
      className={cn(
        "border-b border-border-strong px-3 py-2 font-mono text-2xs font-medium " +
          "tracking-widest text-ink-subtle uppercase",
        numeric ? "text-right" : "text-left",
        className,
      )}
      {...props}
    />
  );
}

export function TD({
  className,
  numeric,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement> & CellProps) {
  return (
    <td
      className={cn(
        "px-3 py-1.5 align-middle",
        numeric && "text-right tnum",
        className,
      )}
      {...props}
    />
  );
}

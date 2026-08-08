import type { HTMLAttributes, ThHTMLAttributes, TdHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * Table primitives.
 *
 * Two decisions worth knowing:
 *  - `numeric` right-aligns and switches to tabular figures. Numbers compare by
 *    their right edge, so left-aligned currency in a column is genuinely harder
 *    to scan.
 *  - The header is sticky, because an inventory table is 200 rows long and a
 *    column heading you have scrolled past is a column heading you don't have.
 */

export function TableWrap({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("overflow-x-auto", className)} {...props} />;
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
      className={cn(
        "sticky top-0 z-10 bg-sunken/90 backdrop-blur-sm",
        className,
      )}
      {...props}
    />
  );
}

export function TBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("divide-y divide-border", className)} {...props} />;
}

export function TR({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn("transition-colors hover:bg-sunken/60", className)}
      {...props}
    />
  );
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
        "border-b border-border px-4 py-2.5 text-2xs font-medium tracking-wider " +
          "text-ink-subtle uppercase",
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
        "px-4 py-2.5 align-middle",
        numeric && "text-right tnum",
        className,
      )}
      {...props}
    />
  );
}

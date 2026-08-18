import type { InputHTMLAttributes, ReactNode } from "react";
import { useId } from "react";

import { cn } from "@/lib/utils";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  /** Shown under the field. Replaced by `error` when there is one. */
  hint?: string;
  error?: string;
  /** Rendered inside the field on the left — a search or currency glyph. */
  icon?: ReactNode;
  /**
   * Rendered inside the field on the right, and unlike `icon` it stays
   * interactive — this is where a reveal-password toggle or a clear button
   * goes. The input gets matching right padding so text never runs under it.
   */
  trailing?: ReactNode;
}

export function Input({
  className,
  label,
  hint,
  error,
  icon,
  trailing,
  id,
  ...props
}: InputProps) {
  // useId so a label always points at its own input, even with several on a page.
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;

  return (
    <div className="w-full">
      {label && (
        <label
          htmlFor={inputId}
          className="mb-1.5 block text-sm font-medium text-ink"
        >
          {label}
        </label>
      )}

      <div className="relative">
        {icon && (
          <span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-subtle">
            {icon}
          </span>
        )}
        <input
          id={inputId}
          // Screen readers announce the error; the red border alone would not.
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(
            "h-9 w-full rounded-md border bg-surface px-3 text-base text-ink " +
              "placeholder:text-ink-subtle " +
              "transition-colors focus:outline-none " +
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent " +
              "disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-subtle",
            icon && "pl-9",
            trailing && "pr-10",
            error ? "border-danger" : "border-border-strong",
            className,
          )}
          {...props}
        />
        {trailing && (
          <span className="absolute top-1/2 right-2 -translate-y-1/2">{trailing}</span>
        )}
      </div>

      {error ? (
        <p id={`${inputId}-error`} className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="mt-1.5 text-xs text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

const button = cva(
  // Shared by every variant: layout, transition, focus ring, disabled state.
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md " +
    "font-medium transition-all duration-150 " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent " +
    "disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        // Exactly one primary action per view. If two things are terracotta,
        // neither reads as the thing to click.
        primary:
          "bg-accent text-white shadow-xs hover:bg-accent-hover active:translate-y-px",
        secondary:
          "bg-surface text-ink border border-border-strong shadow-xs " +
          "hover:bg-sunken active:translate-y-px",
        ghost: "text-ink-muted hover:bg-sunken hover:text-ink",
        danger:
          "bg-danger text-white shadow-xs hover:brightness-110 active:translate-y-px",
        link: "text-accent underline-offset-4 hover:underline p-0 h-auto",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4 text-base",
        lg: "h-11 px-6 text-lg",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  className,
  variant,
  size,
  loading = false,
  icon,
  children,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(button({ variant, size }), className)}
      // A loading button must not be clickable twice — that is how you get
      // duplicate orders.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

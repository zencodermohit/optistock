/**
 * The light/dark switch in the top bar.
 *
 * Drawn as one object with two states rather than two buttons, because that is
 * what it is: a thing that is currently in one position and can be put in the
 * other. A segmented pair would claim the same visual weight as the primary
 * navigation beside it, for a control most people touch once.
 *
 * The two icons occupy the same square and cross-fade through a quarter turn,
 * so the switch reads as one object rotating rather than two icons swapping.
 * Both are always mounted -- animating between two elements that unmount is
 * how you get a flicker at the halfway point.
 *
 * What is showing is announced rather than implied. `aria-pressed` carries the
 * state, and the label says what the button will DO ("Switch to dark") rather
 * than what is currently true, which is the distinction between a control and
 * a status light.
 */

import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

export function ThemeToggle({ className }: { className?: string }) {
  const { appearance, toggle } = useTheme();
  const dark = appearance === "dark";
  const next = dark ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={dark}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      className={cn(
        // Sized to the role chip beside it so the bar keeps one rhythm.
        "group relative inline-flex h-8 w-8 shrink-0 items-center justify-center",
        "rounded-lg border border-border text-ink-muted",
        "transition-colors duration-150",
        "hover:border-border-strong hover:bg-sunken hover:text-ink",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        className,
      )}
    >
      {/* A faint wash that warms on hover -- amber going into the night, cool
          blue coming back out of it. It is the only place in the product where
          the accent is allowed to be decorative, and it stays under 10% so it
          never competes with a status hue. */}
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-0 rounded-lg opacity-0",
          "transition-opacity duration-200 group-hover:opacity-100",
          dark ? "bg-accent/10" : "bg-warning/10",
        )}
      />

      <Sun
        aria-hidden
        className={cn(
          "absolute h-4 w-4 transition-all duration-300 ease-out",
          dark
            ? "scale-50 -rotate-90 opacity-0"
            : "scale-100 rotate-0 opacity-100",
        )}
      />
      <Moon
        aria-hidden
        className={cn(
          "absolute h-4 w-4 transition-all duration-300 ease-out",
          dark
            ? "scale-100 rotate-0 opacity-100"
            : "scale-50 rotate-90 opacity-0",
        )}
      />
    </button>
  );
}

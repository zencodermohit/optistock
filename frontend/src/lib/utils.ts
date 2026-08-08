import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names, letting later Tailwind classes win over earlier ones.
 *
 * Plain string concatenation produces `"px-2 px-4"` and the browser applies
 * whichever CSS rule came last in the stylesheet — not the one you passed last.
 * twMerge resolves the conflict by intent, so a caller can always override a
 * component's defaults.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

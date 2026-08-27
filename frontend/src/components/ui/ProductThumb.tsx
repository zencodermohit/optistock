/**
 * A product's photograph, or a considered stand-in for one.
 *
 * Two hundred of these render in one table, so everything here is about not
 * paying two hundred times for something:
 *
 * *   **The box is sized before the image arrives.** Width and height are set
 *     on the element, so the row reserves its space immediately. Without that,
 *     every picture that loads shoves the rows below it down, and a table of
 *     two hundred settles for several seconds while somebody is trying to read
 *     it -- the effect a projector shows most cruelly.
 * *   **Off-screen images are never fetched.** `loading="lazy"` means the
 *     browser requests what is in view and nothing else; scrolling fetches the
 *     rest. On a 204-row catalogue that is the difference between about a
 *     dozen requests and all of them.
 * *   **Decoding happens off the main thread.** `decoding="async"` keeps image
 *     decode from blocking the scroll it was supposed to accompany.
 *
 * A product with no photograph gets a lettered tile in its category's colour.
 * Not a grey "no image" glyph: that reads as a fault, and there is no fault
 * here -- most catalogues have gaps, and the tile is a real design for the
 * ordinary case rather than an apology for it. It also costs nothing to draw,
 * which matters when it might be drawn two hundred times.
 */

import { useState } from "react";

import { cn } from "@/lib/utils";

/** Deterministic so a product's tile is the same colour on every screen. */
const TILE = [
  "bg-accent-soft text-accent",
  "bg-capacity-soft text-capacity",
  "bg-success-soft text-success",
  "bg-warning-soft text-warning",
  "bg-info-soft text-info",
] as const;

function tileFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  }
  return TILE[Math.abs(hash) % TILE.length];
}

const SIZES = {
  sm: { box: "h-8 w-8 rounded-md", type: "text-2xs", px: 32 },
  md: { box: "h-10 w-10 rounded-md", type: "text-xs", px: 40 },
  lg: { box: "h-20 w-20 rounded-lg", type: "text-lg", px: 80 },
} as const;

export function ProductThumb({
  src,
  name,
  size = "sm",
  className,
}: {
  src?: string | null;
  name: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  // A path that 404s falls back to the tile rather than to a browser's broken
  // image glyph, which is the one thing on this page nobody chose.
  const [failed, setFailed] = useState(false);
  const spec = SIZES[size];
  const shell = cn(
    "shrink-0 overflow-hidden border border-border",
    spec.box,
    className,
  );

  if (!src || failed) {
    return (
      <div
        aria-hidden
        className={cn(
          shell,
          "flex items-center justify-center font-semibold",
          spec.type,
          tileFor(name),
        )}
      >
        {name.trim().charAt(0).toUpperCase() || "?"}
      </div>
    );
  }

  return (
    <img
      src={src}
      // Empty, not the product name. The name is already in the cell beside
      // this, and a screen reader announcing it twice per row makes a table of
      // two hundred products twice as long to listen to.
      alt=""
      width={spec.px}
      height={spec.px}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className={cn(shell, "bg-surface object-contain")}
    />
  );
}

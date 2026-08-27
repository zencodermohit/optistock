import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A product's photograph, or a generated stand-in when there isn't one.
 *
 * This began as the stand-in alone, because Product had no image column and
 * there were no photographs for two hundred SKUs. Both of those are now false,
 * so the photograph comes first and the generated mark became the fallback --
 * which is the shape it should have had all along.
 *
 * The fallback is worth keeping rather than replacing with a grey placeholder.
 * It is DETERMINISTIC: the same SKU draws the same mark on every screen,
 * forever, with no storage and no empty state. Colour comes from the category,
 * so a wall of Furniture reads as one family; the glyph comes from a hash of
 * the SKU, so two products in the same category still look different. A gap in
 * a catalogue is ordinary, and this dresses it as a design rather than a fault.
 *
 * Everything about the image path is sized for lists: two hundred of these can
 * be on screen at once, so the box is sized before the image arrives (nothing
 * reflows), off-screen images are never requested, and decode happens off the
 * main thread. A path that 404s falls back to the mark rather than to the
 * browser's broken-image glyph.
 */

/** Category → the pair of tokens its mark is drawn in. Anything unrecognised
 *  falls back to the neutral pair rather than picking a colour at random. */
const FAMILY: Record<string, { bg: string; fg: string }> = {
  Electronics: { bg: "bg-accent-soft", fg: "text-accent" },
  Furniture: { bg: "bg-capacity-soft", fg: "text-capacity" },
  "Office Supplies": { bg: "bg-warning-soft", fg: "text-warning" },
  Networking: { bg: "bg-info-soft", fg: "text-info" },
  "Safety & PPE": { bg: "bg-danger-soft", fg: "text-danger" },
  Packaging: { bg: "bg-success-soft", fg: "text-success" },
};
const NEUTRAL = { bg: "bg-sunken", fg: "text-ink-muted" };

/** Four glyph families, picked by SKU hash. Geometric rather than pictorial:
 *  a tiny drawing of a chair helps nobody, and a distinct SHAPE is what the eye
 *  actually uses to tell two rows apart. */
const GLYPHS = [
  // stacked bars
  "M4 13h4v7H4zM10 8h4v12h-4zM16 4h4v16h-4z",
  // nested squares
  "M4 4h16v16H4zm4 4h8v8H8z",
  // circles
  "M12 3a9 9 0 100 18 9 9 0 000-18zm0 5a4 4 0 110 8 4 4 0 010-8z",
  // diagonal weave
  "M3 12L12 3l9 9-9 9zM12 8l-4 4 4 4 4-4z",
];

function hash(value: string): number {
  let h = 0;
  for (let i = 0; i < value.length; i++) {
    // Deliberately a plain rolling hash. It only needs to spread evenly across
    // four glyphs, not resist anybody.
    h = (h * 31 + value.charCodeAt(i)) >>> 0;
  }
  return h;
}

const PIXELS = { sm: 32, md: 40, lg: 56 } as const;

export function ProductMark({
  sku,
  category,
  imageUrl,
  size = "md",
}: {
  sku: string;
  category?: string | null;
  /** Path to the product's photograph. Absent or null draws the mark. */
  imageUrl?: string | null;
  size?: "sm" | "md" | "lg";
}) {
  const [failed, setFailed] = useState(false);
  const family = (category && FAMILY[category]) || NEUTRAL;
  const glyph = GLYPHS[hash(sku) % GLYPHS.length];
  const box =
    size === "lg" ? "h-14 w-14" : size === "sm" ? "h-8 w-8" : "h-10 w-10";
  const icon =
    size === "lg" ? "h-7 w-7" : size === "sm" ? "h-4 w-4" : "h-5 w-5";

  if (imageUrl && !failed) {
    return (
      <img
        src={imageUrl}
        // Empty, not the product name. The name is already beside this on
        // every screen that uses it, and announcing it twice per row makes a
        // list of two hundred twice as long to listen to.
        alt=""
        width={PIXELS[size]}
        height={PIXELS[size]}
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className={cn(
          "shrink-0 rounded-xl border border-border bg-surface object-contain",
          box,
        )}
      />
    );
  }

  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-xl border border-border",
        box,
        family.bg,
      )}
    >
      <svg
        viewBox="0 0 24 24"
        className={cn(icon, family.fg)}
        fill="currentColor"
      >
        <path d={glyph} opacity="0.85" />
      </svg>
    </span>
  );
}

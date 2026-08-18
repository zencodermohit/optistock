/**
 * The cube mark — the sign-in page's logo, and only the sign-in page's.
 *
 * Elsewhere the product signs itself with `Mark`, two inked rules on a solid
 * ground, because that is the same device the tables are built from. The door
 * is allowed a different argument: a box, drawn as an object with three lit
 * faces, because the thing behind the door is a building full of them.
 *
 * Drawn as a real isometric solid rather than a flat glyph. The three faces are
 * one hue at three lightnesses, which is what makes a cube read as a cube
 * without any outline doing the work.
 */
export function CubeMark({ size = 40 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden
      className="shrink-0"
    >
      {/* Top face — catches the most light. */}
      <path d="M24 4 43 15 24 26 5 15 24 4Z" fill="#7C93FF" />
      {/* Right face — the mid tone, and the one the eye reads as the body. */}
      <path d="M43 15v18L24 44V26l19-11Z" fill="#3B4FE0" />
      {/* Left face — in shadow, so the two verticals separate at the corner. */}
      <path d="M5 15v18l19 11V26L5 15Z" fill="#2A38B0" />
      {/* A single specular edge along the top-left arris. Without it the mark
          goes flat at favicon sizes, where the face tones converge. */}
      <path
        d="M24 4 5 15"
        stroke="#A8B8FF"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.9"
      />
    </svg>
  );
}

/**
 * Wordmark: "Opti" in the reading ink, "Stock" in the accent.
 *
 * Takes its colours from props rather than tokens because it is set on both the
 * night panel and the white card, and a wordmark that hard-codes one ground is
 * a wordmark you cannot move.
 */
export function CubeWordmark({
  size = 40,
  className = "",
  tone = "ink",
}: {
  size?: number;
  className?: string;
  /** `ink` for the light card, `night` for the dark panel. */
  tone?: "ink" | "night";
}) {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <CubeMark size={size} />
      <span
        className="font-display leading-none font-bold tracking-tight"
        style={{ fontSize: size * 0.72 }}
      >
        <span className={tone === "night" ? "text-night-ink" : "text-ink"}>Opti</span>
        <span className={tone === "night" ? "text-night-accent" : "text-accent"}>
          Stock
        </span>
      </span>
    </div>
  );
}

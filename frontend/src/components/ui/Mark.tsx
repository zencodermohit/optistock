/**
 * The mark: the greenbar itself, at whatever size you ask for. Two inked rules
 * on a solid ground — the same device the tables use, so the logo and the data
 * are made of the same thing rather than the logo being a shape borrowed from
 * somewhere else.
 */
export function Mark({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 18 18"
      aria-hidden
      className="shrink-0"
    >
      <rect width="18" height="18" rx="2" fill="var(--color-accent)" />
      {[3.5, 8.5].map((y) => (
        <rect
          key={y}
          x="3"
          y={y}
          width="12"
          height="2.5"
          rx="0.5"
          fill="var(--color-surface)"
          opacity="0.9"
        />
      ))}
    </svg>
  );
}

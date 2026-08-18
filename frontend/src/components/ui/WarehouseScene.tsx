/**
 * An isometric warehouse, drawn as geometry rather than art.
 *
 * This is a stand-in, and it is built to be replaced. The sign-in page takes a
 * licensed render if one is supplied and falls back to this; see the note at the
 * top of Login.tsx. Everything here is original and carries no licence, so the
 * page is complete and shippable in the meantime rather than waiting on an
 * asset purchase.
 *
 * WHY GEOMETRY AND NOT PATHS. A hand-authored isometric scene is a few hundred
 * unreadable path commands that nobody can adjust afterwards — moving one crate
 * means recomputing twelve coordinates by hand. Every solid here is instead one
 * `Box` in world coordinates, and the projection and the shading are computed.
 * A crate moves by changing a number.
 *
 * THE PROJECTION. Standard 2:1-ish isometric, viewed from front-top-right:
 *
 *     screen x = (x - z) · cos30        y is up
 *     screen y = (x + z) · sin30 - y    x runs right-and-down, z left-and-down
 *
 * So exactly three faces of any box are visible — the top, the face at max x,
 * and the face at max z — and each is one hue at a different lightness. That
 * tonal step is the whole illusion; there is not a single outline in the scene.
 *
 * DRAW ORDER IS MANUAL, NOT SORTED. A painter's-algorithm sort on box centres
 * gets the ground plane wrong (the platform's centre is deeper than everything
 * standing on it, so it paints over the lot) and gets shelves wrong (a crate
 * sitting at the front of a shelf has a shallower centre than the board beneath
 * it). The scene is authored back-to-front instead, which is deterministic and
 * can actually be debugged by reading it.
 */

const U = 15; // world unit → px
const OX = 255; // screen origin
const OY = 130;

const COS30 = 0.8660254;

/** World point → screen point. */
function project(x: number, y: number, z: number): string {
  return `${OX + (x - z) * COS30 * U},${OY + (x + z) * 0.5 * U - y * U}`;
}

/** Multiply a hex colour's channels, for the two shaded faces. */
function shade(hex: string, factor: number): string {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) =>
    Math.max(0, Math.min(255, Math.round(c * factor))),
  );
  return `#${((ch[0] << 16) | (ch[1] << 8) | ch[2]).toString(16).padStart(6, "0")}`;
}

interface BoxProps {
  x: number;
  y: number;
  z: number;
  w: number;
  h: number;
  d: number;
  c: string;
  /** Skip the top face for something tucked under another solid. */
  flat?: boolean;
}

/**
 * One solid. Three polygons, one hue, three lightnesses: the top takes the
 * light, the +x face sits mid, the +z face falls away.
 */
function Box({ x, y, z, w, h, d, c, flat }: BoxProps) {
  const top = [
    project(x, y + h, z),
    project(x + w, y + h, z),
    project(x + w, y + h, z + d),
    project(x, y + h, z + d),
  ].join(" ");

  const right = [
    project(x + w, y, z),
    project(x + w, y + h, z),
    project(x + w, y + h, z + d),
    project(x + w, y, z + d),
  ].join(" ");

  const left = [
    project(x, y, z + d),
    project(x, y + h, z + d),
    project(x + w, y + h, z + d),
    project(x + w, y, z + d),
  ].join(" ");

  return (
    <g>
      <polygon points={left} fill={shade(c, 0.62)} />
      <polygon points={right} fill={shade(c, 0.82)} />
      {!flat && <polygon points={top} fill={c} />}
    </g>
  );
}

/* --- Palette -----------------------------------------------------------------
   Warm solids on a cool night ground. The scene deliberately does NOT reuse the
   product's semantic tokens: amber and red mean stock trouble on every screen
   behind this one, and a crate that happens to be orange must not read as an
   alarm. These are object colours, not status colours. */
/* A step cooler and darker than it first was. The van and the wrapped pallets
   are near-white, and on a pale slab they dissolved into the floor — the solids
   have to out-value the ground they stand on. */
const SLAB = "#aab8d2";
const STEEL = "#93a3bd";
const KRAFT = "#dcb283";
const CLAY = "#e07a5f";
const SAGE = "#7fae9b";
const BLUE = "#6c85ff";
const AMBER = "#efb75f";
const SHELL = "#eef2f9";
const TYRE = "#3a4356";

/** A run of crates along a shelf, alternating so no two neighbours match. */
function Crates({
  x,
  y,
  z,
  colors,
}: {
  x: number;
  y: number;
  z: number;
  colors: string[];
}) {
  return (
    <>
      {colors.map((c, i) => (
        <Box
          key={i}
          x={x + i * 1.75}
          y={y}
          z={z}
          w={1.5}
          h={1.15}
          d={1.5}
          c={c}
        />
      ))}
    </>
  );
}

export function WarehouseScene({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 560 440"
      className={className}
      role="img"
      aria-label="An isometric illustration of a warehouse: racking stacked with
        crates, a delivery van being loaded, a conveyor and an autonomous floor
        robot."
    >
      <defs>
        {/* Contact shadow. The slab is the only thing that needs grounding —
            everything else sits on it and reads as attached. */}
        <radialGradient id="ws-ground" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#0a1128" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#060c1c" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* ---- Ground -------------------------------------------------------- */}
      <ellipse cx="272" cy="330" rx="240" ry="96" fill="url(#ws-ground)" />
      <Box x={0} y={-1.2} z={0} w={20} h={1.2} d={16} c={SLAB} />

      {/* ---- Racking, back left -------------------------------------------
          Authored bottom shelf upward: each board, then what sits on it. */}
      <Box x={1.4} y={0} z={0.9} w={0.35} h={6.6} d={0.35} c={STEEL} />
      <Box x={9.1} y={0} z={0.9} w={0.35} h={6.6} d={0.35} c={STEEL} />

      <Box x={1.4} y={1.4} z={0.9} w={8.05} h={0.28} d={2.6} c={STEEL} />
      <Crates x={1.7} y={1.68} z={1.4} colors={[KRAFT, CLAY, KRAFT, SAGE]} />

      <Box x={1.4} y={3.3} z={0.9} w={8.05} h={0.28} d={2.6} c={STEEL} />
      <Crates x={1.7} y={3.58} z={1.4} colors={[SAGE, KRAFT, AMBER, KRAFT]} />

      <Box x={1.4} y={5.2} z={0.9} w={8.05} h={0.28} d={2.6} c={STEEL} />
      <Crates x={1.7} y={5.48} z={1.4} colors={[KRAFT, SHELL, CLAY, KRAFT]} />

      <Box x={1.4} y={0} z={3.15} w={0.35} h={6.6} d={0.35} c={STEEL} />
      <Box x={9.1} y={0} z={3.15} w={0.35} h={6.6} d={0.35} c={STEEL} />

      {/* ---- Conveyor, middle ---------------------------------------------- */}
      <Box x={11.2} y={0} z={1.4} w={5.6} h={0.7} d={1.7} c={STEEL} />
      <Box x={11.2} y={0.7} z={1.5} w={5.6} h={0.18} d={1.5} c={SAGE} />
      <Box x={12.1} y={0.88} z={1.75} w={1.1} h={0.85} d={1.1} c={KRAFT} />
      <Box x={14.3} y={0.88} z={1.75} w={1.1} h={0.85} d={1.1} c={CLAY} />

      {/* ---- Pallet stack, mid left ---------------------------------------- */}
      <Box x={2.6} y={0} z={6.4} w={2.9} h={0.4} d={2.6} c={KRAFT} />
      <Box x={2.8} y={0.4} z={6.6} w={2.5} h={1.3} d={2.2} c={SHELL} />
      <Box x={2.9} y={1.7} z={6.7} w={2.2} h={1.1} d={2} c={CLAY} />

      {/* ---- Empty pallets, stacked to the right of the conveyor ----------- */}
      <Box x={17.1} y={0} z={3.6} w={2.4} h={0.35} d={2.2} c={KRAFT} />
      <Box x={17.1} y={0.35} z={3.6} w={2.4} h={0.35} d={2.2} c={KRAFT} />
      <Box x={17.1} y={0.7} z={3.6} w={2.4} h={0.35} d={2.2} c={KRAFT} />

      {/* ---- The van, right ------------------------------------------------
          Wheels first: they sit under the body, so they are behind it in the
          only sense this projection has. */}
      <Box x={12.4} y={0} z={7.5} w={0.7} h={0.75} d={1.1} c={TYRE} />
      <Box x={12.4} y={0} z={10.1} w={0.7} h={0.75} d={1.1} c={TYRE} />
      <Box x={16.9} y={0} z={7.5} w={0.7} h={0.75} d={1.1} c={TYRE} />
      <Box x={16.9} y={0} z={10.1} w={0.7} h={0.75} d={1.1} c={TYRE} />

      {/* Cargo box, then the lower cab ahead of it. */}
      <Box x={11.9} y={0.7} z={7.2} w={4.2} h={3.1} d={4.2} c={SHELL} />
      <Box x={16.1} y={0.7} z={7.4} w={2.2} h={2.2} d={3.8} c={SHELL} />
      {/* Windscreen and a lamp, the two details that make it a vehicle. */}
      <Box x={18.28} y={1.5} z={7.6} w={0.06} h={1.2} d={3.4} c="#4a5a78" />
      <Box x={18.3} y={0.95} z={7.7} w={0.08} h={0.35} d={0.7} c={AMBER} />
      {/* Open rear door and a crate part-loaded — the scene is mid-task. */}
      <Box x={11.82} y={0.9} z={7.4} w={0.08} h={2.7} d={3.8} c={SAGE} />
      <Box x={10.3} y={0} z={8.4} w={1.4} h={1.15} d={1.4} c={KRAFT} />

      {/* ---- Floor robot, front -------------------------------------------- */}
      <Box x={6.6} y={0} z={11.4} w={0.45} h={0.4} d={0.9} c={TYRE} />
      <Box x={8.1} y={0} z={11.4} w={0.45} h={0.4} d={0.9} c={TYRE} />
      <Box x={6.5} y={0.35} z={11.2} w={2.2} h={0.75} d={1.4} c={BLUE} />
      <Box x={6.8} y={1.1} z={11.45} w={1.6} h={1.2} d={0.95} c={KRAFT} />

      {/* ---- Wrapped pallet, front left ------------------------------------
          Fills the corner the slab was otherwise showing bare, and gives the
          robot something to be heading towards. */}
      <Box x={1.6} y={0} z={11.6} w={2.4} h={0.35} d={2.2} c={KRAFT} />
      <Box x={1.75} y={0.35} z={11.75} w={2.1} h={2.1} d={1.9} c={SHELL} />
      <Box x={1.72} y={1.1} z={11.72} w={2.16} h={0.5} d={1.96} c={SAGE} />

      {/* ---- Loose stock, front right -------------------------------------- */}
      <Box x={12.5} y={0} z={12.4} w={1.6} h={1.3} d={1.6} c={CLAY} />
      <Box x={12.7} y={1.3} z={12.6} w={1.2} h={1} d={1.2} c={KRAFT} />
      <Box x={14.6} y={0} z={12.9} w={1.3} h={0.95} d={1.3} c={SAGE} />
    </svg>
  );
}

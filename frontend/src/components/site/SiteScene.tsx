import { ContactShadows, Html, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import type { Group, Mesh } from "three";

import type { SiteWarehouse } from "@/lib/queries";

/**
 * The site, in three dimensions.
 *
 * Every dimension here is a measurement. A building's footprint comes from its
 * capacity in units, the lit band up its face is how full it currently is, and
 * the marker floating above it appears only when that warehouse has stock lines
 * at zero. Nothing is placed because it looked balanced.
 *
 * That constraint is the whole reason this is worth building. A rendered
 * warehouse that ignores the data is a photograph — pleasant on login and
 * useless by the second visit. This one is read: the tallest building is the
 * one holding the most, and the red pin is where somebody needs to go today.
 *
 * Deliberately no environment map or loaded model. Both would mean a network
 * fetch to a CDN before the landing screen could draw, and the scene is simple
 * enough that three lights and a contact shadow do better work than an HDR.
 */

/* Mirrors the tokens in index.css. Duplicated rather than read from
   getComputedStyle because a WebGL material needs a value at construction and
   re-reading CSS on every frame is a cost with no benefit — but if the palette
   moves, these move with it. */
const PALETTE = {
  ground: "#e6ebf5",
  road: "#d5dce9",
  wall: "#ffffff",
  wallShaded: "#eef1f7",
  roof: "#dfe5f0",
  accent: "#4460f0",
  capacity: "#7c5cf5",
  warning: "#b26a06",
  danger: "#c0392f",
  foliage: "#8fa8dd",
  trunk: "#c3cbdb",
};

/** Footprint and height from capacity, on a gentle curve.
 *
 * Linear scaling would make Bangalore (25,000) look like a shed beside Mumbai
 * (50,000) and the smaller sites would be unreadable. A square root keeps the
 * ordering honest — bigger is still bigger — while leaving every building large
 * enough to carry a label and a pin.
 */
function dimensions(capacity: number, largest: number) {
  const ratio = largest > 0 ? capacity / largest : 1;
  const scale = Math.sqrt(Math.max(ratio, 0.16));
  return {
    width: 3.6 * scale + 1.4,
    depth: 2.6 * scale + 1.1,
    height: 1.5 * scale + 0.7,
  };
}

function Building({
  warehouse,
  position,
  size,
  selected,
  onSelect,
}: {
  warehouse: SiteWarehouse;
  position: [number, number, number];
  size: { width: number; depth: number; height: number };
  selected: boolean;
  onSelect: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const pin = useRef<Group>(null);

  const fill = warehouse.utilisation ?? 0;
  const inTrouble = warehouse.out_lines > 0;
  const lift = selected ? 0.16 : hovered ? 0.07 : 0;

  // The pin bobs. It is the one moving thing in the scene, which is what makes
  // it the thing you look at — and it only exists when something is wrong.
  useFrame(({ clock }) => {
    if (pin.current) {
      pin.current.position.y =
        size.height + 0.85 + Math.sin(clock.elapsedTime * 1.8) * 0.07;
    }
  });

  return (
    <group
      position={[position[0], position[1] + lift, position[2]]}
      onPointerOver={(e) => {
        e.stopPropagation();
        setHovered(true);
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = "";
      }}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
    >
      {/* Body */}
      <mesh castShadow receiveShadow position={[0, size.height / 2, 0]}>
        <boxGeometry args={[size.width, size.height, size.depth]} />
        <meshStandardMaterial
          color={selected || hovered ? PALETTE.wall : PALETTE.wallShaded}
          roughness={0.72}
          metalness={0.04}
        />
      </mesh>

      {/* Roof cap — a flat slab, slightly proud, so the box reads as a building
          rather than a cube. */}
      <mesh castShadow position={[0, size.height + 0.045, 0]}>
        <boxGeometry args={[size.width + 0.12, 0.09, size.depth + 0.12]} />
        <meshStandardMaterial color={PALETTE.roof} roughness={0.85} />
      </mesh>

      {/* THE FILL BAND — how full this warehouse is, drawn up the front face.
          Violet because capacity is a neutral fact about a building; it must
          never be mistaken for the alarm hues. */}
      <mesh position={[0, (size.height * fill) / 2, size.depth / 2 + 0.012]}>
        <planeGeometry args={[size.width * 0.82, Math.max(size.height * fill, 0.02)]} />
        <meshBasicMaterial color={PALETTE.capacity} transparent opacity={0.82} />
      </mesh>
      {/* The remaining capacity, ghosted, so the bar is legible as a proportion
          rather than as an absolute smear of colour. */}
      <mesh position={[0, size.height / 2, size.depth / 2 + 0.008]}>
        <planeGeometry args={[size.width * 0.82, size.height]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.34} />
      </mesh>

      {/* Selection ring */}
      {(selected || hovered) && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.012, 0]}>
          <ringGeometry
            args={[
              Math.max(size.width, size.depth) * 0.72,
              Math.max(size.width, size.depth) * 0.78,
              48,
            ]}
          />
          <meshBasicMaterial color={PALETTE.accent} transparent opacity={selected ? 0.95 : 0.5} />
        </mesh>
      )}

      {/* Trouble marker — present only when stock is actually at zero here. */}
      {inTrouble && (
        <group ref={pin} position={[0, size.height + 0.85, 0]}>
          <mesh>
            <sphereGeometry args={[0.16, 20, 20]} />
            <meshStandardMaterial
              color={PALETTE.danger}
              emissive={PALETTE.danger}
              emissiveIntensity={0.55}
            />
          </mesh>
          <mesh position={[0, -0.28, 0]}>
            <coneGeometry args={[0.1, 0.34, 18]} />
            <meshStandardMaterial color={PALETTE.danger} />
          </mesh>
        </group>
      )}

      {/* Label. An HTML overlay rather than 3D text: it stays crisp at every
          zoom, uses the page's real typeface, and is readable by a screen
          reader — none of which is true of extruded geometry. */}
      <Html
        position={[0, size.height + (inTrouble ? 1.5 : 0.55), 0]}
        center
        distanceFactor={11}
        zIndexRange={[20, 0]}
      >
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onSelect();
          }}
          className={[
            "pointer-events-auto flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5",
            "font-display text-[13px] font-bold whitespace-nowrap shadow-md transition-colors",
            selected
              ? "border-accent bg-accent text-white"
              : "border-border bg-surface/95 text-ink hover:border-accent-border",
          ].join(" ")}
        >
          {warehouse.name}
          <span
            className={[
              "tnum rounded-full px-1.5 py-px text-[11px] font-semibold",
              selected ? "bg-white/20 text-white" : "bg-sunken text-ink-muted",
            ].join(" ")}
          >
            {warehouse.utilisation != null
              ? `${Math.round(warehouse.utilisation * 100)}%`
              : "—"}
          </span>
        </button>
      </Html>
    </group>
  );
}

/** Low decoration, kept deliberately sparse. Enough to read as a site rather
 *  than boxes on a plane; not so much that it competes with the buildings. */
function Tree({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh position={[0, 0.16, 0]} castShadow>
        <cylinderGeometry args={[0.035, 0.05, 0.32, 6]} />
        <meshStandardMaterial color={PALETTE.trunk} roughness={0.9} />
      </mesh>
      <mesh position={[0, 0.48, 0]} castShadow>
        <icosahedronGeometry args={[0.28, 0]} />
        <meshStandardMaterial color={PALETTE.foliage} roughness={0.85} flatShading />
      </mesh>
    </group>
  );
}

function Site({
  warehouses,
  selectedId,
  onSelect,
}: {
  warehouses: SiteWarehouse[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const largest = Math.max(...warehouses.map((w) => w.capacity_units), 1);

  // Laid out along a service road rather than on a grid, because a row of
  // buildings facing one access route is what a distribution site actually
  // looks like — and it keeps every label readable from the default camera.
  const placed = useMemo(() => {
    const spacing = 5.2;
    const offset = ((warehouses.length - 1) * spacing) / 2;
    return warehouses.map((warehouse, i) => ({
      warehouse,
      size: dimensions(warehouse.capacity_units, largest),
      position: [i * spacing - offset, 0, i % 2 === 0 ? -0.9 : 1.1] as [
        number,
        number,
        number,
      ],
    }));
  }, [warehouses, largest]);

  const trees = useMemo(() => {
    const spots: [number, number, number][] = [];
    const span = ((warehouses.length - 1) * 5.2) / 2 + 4;
    for (let i = 0; i < 26; i++) {
      const x = -span + (i / 25) * span * 2;
      spots.push([x + (i % 3) * 0.4, 0, i % 2 === 0 ? -5.4 : 5.6]);
    }
    return spots;
  }, [warehouses.length]);

  return (
    <>
      <ambientLight intensity={0.85} />
      <directionalLight
        position={[7, 11, 6]}
        intensity={1.5}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-18}
        shadow-camera-right={18}
        shadow-camera-top={18}
        shadow-camera-bottom={-18}
      />
      <directionalLight position={[-8, 5, -6]} intensity={0.35} />

      {/* Ground */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]} receiveShadow>
        <planeGeometry args={[80, 60]} />
        <meshStandardMaterial color={PALETTE.ground} roughness={1} />
      </mesh>

      {/* Service road running the length of the site */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.002, 3.3]} receiveShadow>
        <planeGeometry args={[((warehouses.length - 1) * 5.2) + 12, 1.5]} />
        <meshStandardMaterial color={PALETTE.road} roughness={0.95} />
      </mesh>

      {trees.map((position, i) => (
        <Tree key={i} position={position} />
      ))}

      {placed.map(({ warehouse, size, position }) => (
        <Building
          key={warehouse.id}
          warehouse={warehouse}
          position={position}
          size={size}
          selected={selectedId === warehouse.id}
          onSelect={() => onSelect(warehouse.id)}
        />
      ))}

      <ContactShadows
        position={[0, 0.005, 0]}
        opacity={0.34}
        scale={44}
        blur={2.4}
        far={9}
      />
    </>
  );
}

export function SiteScene({
  warehouses,
  selectedId,
  onSelect,
}: {
  warehouses: SiteWarehouse[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  // Honoured rather than assumed: an orbiting camera is exactly the kind of
  // ambient motion that makes some people ill.
  const stillness =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [9, 8, 13], fov: 38 }}
      style={{ touchAction: "none" }}
    >
      <color attach="background" args={["#f5f7fb"]} />
      <fog attach="fog" args={["#f5f7fb", 26, 54]} />
      <Site warehouses={warehouses} selectedId={selectedId} onSelect={onSelect} />
      <OrbitControls
        makeDefault
        enablePan={false}
        autoRotate={!stillness}
        autoRotateSpeed={0.35}
        minPolarAngle={Math.PI / 7}
        // Stops short of the horizon: below this the buildings occlude each
        // other and the scene stops being a site map.
        maxPolarAngle={Math.PI / 2.35}
        minDistance={9}
        maxDistance={30}
      />
    </Canvas>
  );
}

/** A ref type kept for the mesh helpers above. */
export type { Mesh };

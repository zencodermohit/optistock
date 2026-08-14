import {
  ContactShadows,
  Environment,
  Html,
  Lightformer,
  OrbitControls,
} from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import {
  EffectComposer,
  N8AO,
  SMAA,
  Select,
  Selection,
  SelectiveBloom,
} from "@react-three/postprocessing";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DirectionalLight, Group } from "three";

import type { SiteWarehouse } from "@/lib/queries";

/**
 * One site, in three dimensions.
 *
 * Every dimension is a measurement. The building's footprint comes from its
 * capacity in units, the glowing ring at its base is how full it currently is,
 * and the marker above the roof appears only when that site has stock lines
 * actually at zero. Nothing is placed because it looked balanced.
 *
 * Showing one building at a time rather than the whole row was the right call
 * for a reason beyond taste: four buildings in a line meant every one of them
 * was small, occluded from most angles, and unreadable at a glance. A single
 * centred subject can carry loading docks, silos and a legible label — and the
 * comparison between sites moves to the arrows, where switching is a deliberate
 * act rather than a scan.
 *
 * Deliberately no loaded model and no HDR file. Both mean a network fetch to a
 * CDN before the landing screen can draw. The environment here is built from
 * Lightformers — flat emissive planes the renderer treats as a light probe —
 * which gives real reflections in the walls at zero network cost.
 */

/* Mirrors the tokens in index.css. Duplicated rather than read through
   getComputedStyle because a WebGL material needs its value at construction,
   and re-reading CSS every frame costs something and buys nothing. */
/* Values matter more than hues here. The first build put a near-white building
   on a near-white ground and the whole scene read as fog -- there was nothing
   for the eye to catch. Every surface below now sits at a deliberately
   different lightness, and the ground is pushed well down so the building has
   something to stand out against. */
const PALETTE = {
  ground: "#d3dcee",
  road: "#c4cee4",
  apron: "#cad4e8",
  wall: "#fcfdff",
  wallWarm: "#eef2fa",
  roof: "#b9c5dc",
  trim: "#9dabc6",
  glass: "#6b86c4",
  dock: "#46516b",
  capacity: "#7c5cf5",
  danger: "#e0483c",
  foliage: "#6d8ad2",
  foliageDeep: "#4c69b8",
  trunk: "#aab6ce",
  vehicle: "#ffffff",
};

/** Footprint from capacity, on a square-root curve.
 *
 * Linear scaling would render Bangalore (25,000 units) as a shed beside Mumbai
 * (50,000) and the smaller sites would read as broken. A square root keeps the
 * ordering honest — bigger is still visibly bigger — while leaving every site
 * substantial enough to carry docks and a label.
 */
function dimensions(capacity: number, largest: number) {
  const ratio = largest > 0 ? capacity / largest : 1;
  const scale = Math.sqrt(Math.max(ratio, 0.3));
  return {
    width: 5.2 * scale,
    depth: 3.4 * scale,
    height: 1.55 * scale + 0.45,
  };
}

/* ------------------------------------------------------------------ */
/* Parts                                                               */
/* ------------------------------------------------------------------ */

/** Loading bays cut into the long face, with a canopy over them. */
function DockFace({ width, depth, height }: { width: number; depth: number; height: number }) {
  const bays = Math.max(3, Math.min(7, Math.round(width / 0.85)));
  const bayWidth = 0.42;
  const spacing = (width * 0.86) / bays;
  const z = depth / 2;

  return (
    <group>
      {/* Canopy */}
      <mesh position={[0, height * 0.56, z + 0.34]} castShadow>
        <boxGeometry args={[width * 0.92, 0.07, 0.72]} />
        <meshStandardMaterial color={PALETTE.trim} roughness={0.55} metalness={0.15} />
      </mesh>

      {Array.from({ length: bays }).map((_, i) => {
        const x = (i - (bays - 1) / 2) * spacing;
        return (
          <group key={i} position={[x, 0, 0]}>
            {/* Recessed bay */}
            <mesh position={[0, 0.29, z + 0.011]}>
              <planeGeometry args={[bayWidth, 0.58]} />
              <meshStandardMaterial color={PALETTE.dock} roughness={0.9} />
            </mesh>
            {/* Shutter housing */}
            <mesh position={[0, 0.62, z + 0.03]} castShadow>
              <boxGeometry args={[bayWidth + 0.06, 0.08, 0.08]} />
              <meshStandardMaterial color={PALETTE.trim} roughness={0.6} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

/** A delivery van backed onto a bay. Simple masses — at this scale a van is a
 *  silhouette, and detail here would compete with the building. */
function Van({ position, rotation = 0 }: { position: [number, number, number]; rotation?: number }) {
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      <mesh position={[0, 0.19, 0]} castShadow receiveShadow>
        <boxGeometry args={[0.34, 0.32, 0.72]} />
        <meshStandardMaterial color={PALETTE.vehicle} roughness={0.42} metalness={0.2} />
      </mesh>
      <mesh position={[0, 0.14, 0.46]} castShadow>
        <boxGeometry args={[0.32, 0.24, 0.24]} />
        <meshStandardMaterial color={PALETTE.vehicle} roughness={0.42} metalness={0.2} />
      </mesh>
      <mesh position={[0, 0.2, 0.575]}>
        <planeGeometry args={[0.24, 0.12]} />
        <meshStandardMaterial color={PALETTE.glass} roughness={0.15} metalness={0.5} />
      </mesh>
    </group>
  );
}

/** Storage silos on a platform — the detail that makes it read as industrial
 *  rather than as a shopping centre. */
function Silos({ position, count = 5 }: { position: [number, number, number]; count?: number }) {
  return (
    <group position={position}>
      <mesh position={[0, 0.03, 0]} receiveShadow>
        <boxGeometry args={[count * 0.32 + 0.24, 0.06, 0.62]} />
        <meshStandardMaterial color={PALETTE.trim} roughness={0.85} />
      </mesh>
      {Array.from({ length: count }).map((_, i) => (
        <group key={i} position={[(i - (count - 1) / 2) * 0.32, 0, 0]}>
          <mesh position={[0, 0.42, 0]} castShadow>
            <cylinderGeometry args={[0.115, 0.115, 0.72, 16]} />
            <meshStandardMaterial color={PALETTE.wall} roughness={0.35} metalness={0.35} />
          </mesh>
          <mesh position={[0, 0.82, 0]} castShadow>
            <coneGeometry args={[0.118, 0.16, 16]} />
            <meshStandardMaterial color={PALETTE.trim} roughness={0.4} metalness={0.3} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

/** Rooftop plant — HVAC blocks and ducting. */
function RoofPlant({ width, depth, height }: { width: number; depth: number; height: number }) {
  const units = Math.max(2, Math.round(width / 1.6));
  return (
    <group position={[0, height + 0.09, -depth * 0.16]}>
      {Array.from({ length: units }).map((_, i) => (
        <mesh
          key={i}
          position={[(i - (units - 1) / 2) * 0.78, 0.09, 0]}
          castShadow
        >
          <boxGeometry args={[0.44, 0.18, 0.36]} />
          <meshStandardMaterial color={PALETTE.trim} roughness={0.55} metalness={0.25} />
        </mesh>
      ))}
      {/* Rotation belongs on the mesh, not the geometry — a BufferGeometry has
          no transform of its own. */}
      <mesh position={[0, 0.06, depth * 0.28]} rotation={[0, 0, Math.PI / 2]} castShadow>
        <cylinderGeometry args={[0.07, 0.07, width * 0.6, 12]} />
        <meshStandardMaterial color={PALETTE.trim} roughness={0.5} metalness={0.3} />
      </mesh>
    </group>
  );
}

/** The office annex, with a window grid. Sits lower and to one side so the
 *  main shed stays the subject. */
function OfficeAnnex({ position, height }: { position: [number, number, number]; height: number }) {
  const rows = 2;
  const cols = 5;
  const w = 1.5;
  const d = 1.05;
  const h = height * 0.78;

  return (
    <group position={position}>
      <mesh position={[0, h / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial color={PALETTE.wallWarm} roughness={0.45} metalness={0.12} />
      </mesh>
      <mesh position={[0, h + 0.035, 0]} castShadow>
        <boxGeometry args={[w + 0.08, 0.07, d + 0.08]} />
        <meshStandardMaterial color={PALETTE.roof} roughness={0.8} />
      </mesh>
      {Array.from({ length: rows }).map((_, r) =>
        Array.from({ length: cols }).map((_, c) => (
          <mesh
            key={`${r}-${c}`}
            position={[
              (c - (cols - 1) / 2) * (w / cols) * 0.94,
              h * 0.34 + r * (h * 0.3),
              d / 2 + 0.008,
            ]}
          >
            <planeGeometry args={[0.14, 0.13]} />
            <meshStandardMaterial
              color={PALETTE.glass}
              roughness={0.12}
              metalness={0.6}
            />
          </mesh>
        )),
      )}
    </group>
  );
}

function Tree({ position, scale = 1 }: { position: [number, number, number]; scale?: number }) {
  return (
    <group position={position} scale={scale}>
      <mesh position={[0, 0.2, 0]} castShadow>
        <cylinderGeometry args={[0.03, 0.045, 0.4, 6]} />
        <meshStandardMaterial color={PALETTE.trunk} roughness={0.9} />
      </mesh>
      <mesh position={[0, 0.56, 0]} castShadow>
        <icosahedronGeometry args={[0.3, 0]} />
        <meshStandardMaterial color={PALETTE.foliage} roughness={0.85} flatShading />
      </mesh>
      <mesh position={[0.1, 0.4, 0.06]} castShadow>
        <icosahedronGeometry args={[0.19, 0]} />
        <meshStandardMaterial color={PALETTE.foliageDeep} roughness={0.85} flatShading />
      </mesh>
    </group>
  );
}

/**
 * The capacity ring.
 *
 * An arc at the base whose sweep is the site's utilisation, sitting on a faint
 * full-circle track so the reader sees the proportion rather than an isolated
 * glowing smear. This is the one emissive object in the scene, which is why
 * bloom is selective — a global bloom would make the white walls halo and the
 * ring would stop being the brightest thing.
 *
 * A floor is enforced on the sweep. These warehouses run at single-digit
 * utilisation, and a mathematically honest 4% arc is a few invisible pixels;
 * the percentage is stated in the label beside it, so a legible minimum arc
 * costs no accuracy while keeping the ring readable as an object.
 */
function CapacityRing({
  radius,
  utilisation,
}: {
  radius: number;
  utilisation: number;
}) {
  const sweep = Math.max(utilisation, 0.06) * Math.PI * 2;
  const thickness = 0.26;

  return (
    <group position={[0, 0.03, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      {/* A wide, very faint halo under everything, so the ring reads as
          emitting light onto the apron rather than sitting on it like a
          sticker. */}
      <mesh position={[0, 0, -0.004]}>
        <ringGeometry args={[radius - 0.5, radius + thickness + 0.5, 96]} />
        <meshBasicMaterial color={PALETTE.capacity} transparent opacity={0.09} />
      </mesh>

      {/* The unfilled remainder. Visible, or the arc has nothing to be a
          proportion OF. */}
      <mesh>
        <ringGeometry args={[radius, radius + thickness, 96]} />
        <meshBasicMaterial color={PALETTE.capacity} transparent opacity={0.22} />
      </mesh>

      {/* The filled arc. Starts at 12 o'clock. This is the only emissive thing
          in the scene, which is what makes selective bloom worth the cost. */}
      <Select enabled>
        <mesh rotation={[0, 0, Math.PI / 2]}>
          <ringGeometry args={[radius, radius + thickness, 96, 1, 0, sweep]} />
          <meshBasicMaterial color={PALETTE.capacity} toneMapped={false} />
        </mesh>
      </Select>
    </group>
  );
}

/** The trouble marker. Present only when stock is genuinely at zero here. */
function Marker({ height }: { height: number }) {
  const pin = useRef<Group>(null);

  useFrame(({ clock }) => {
    if (pin.current) {
      pin.current.position.y = height + 1.05 + Math.sin(clock.elapsedTime * 1.9) * 0.08;
    }
  });

  return (
    <group ref={pin} position={[0, height + 1.05, 0]}>
      <Select enabled>
        <mesh>
          <sphereGeometry args={[0.15, 22, 22]} />
          <meshBasicMaterial color={PALETTE.danger} toneMapped={false} />
        </mesh>
      </Select>
      <mesh position={[0, -0.26, 0]}>
        <coneGeometry args={[0.09, 0.32, 18]} />
        <meshStandardMaterial color={PALETTE.danger} roughness={0.5} />
      </mesh>
    </group>
  );
}

/* ------------------------------------------------------------------ */
/* The building                                                        */
/* ------------------------------------------------------------------ */

function Warehouse({ warehouse, largest }: { warehouse: SiteWarehouse; largest: number }) {
  const size = dimensions(warehouse.capacity_units, largest);
  const fill = warehouse.utilisation ?? 0;
  const ringRadius = Math.max(size.width, size.depth) * 0.62;

  const vans = useMemo(() => {
    const spots: { position: [number, number, number]; rotation: number }[] = [];
    const n = Math.min(3, Math.max(1, Math.round(size.width / 2)));
    for (let i = 0; i < n; i++) {
      spots.push({
        position: [(i - (n - 1) / 2) * 1.05, 0, size.depth / 2 + 0.92],
        rotation: Math.PI,
      });
    }
    return spots;
  }, [size.width, size.depth]);

  /* A grove, not a scatter. The first pass ringed the building with trees at
     an offset, which spread the visual mass across the whole frame and left the
     composition lopsided. Real sites have planting massed at a boundary, and
     one dense clump reads better than eleven lonely ones. */
  const trees = useMemo(() => {
    const spots: { position: [number, number, number]; scale: number }[] = [];
    const originX = size.width / 2 + 3.1;
    const originZ = -size.depth / 2 - 0.6;
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 3; col++) {
        spots.push({
          position: [
            originX + col * 0.82 + (row % 2) * 0.34,
            0,
            originZ + row * 0.86 + (col % 2) * 0.22,
          ],
          scale: 0.78 + ((row + col) % 3) * 0.16,
        });
      }
    }
    return spots;
  }, [size.width, size.depth]);

  return (
    <group>
      {/* Apron the building stands on — stops it floating on the ground plane */}
      <mesh position={[0, 0.012, 0.3]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[size.width + 3.4, size.depth + 3.6]} />
        <meshStandardMaterial color={PALETTE.apron} roughness={0.95} />
      </mesh>

      {/* Main shed */}
      <mesh position={[0, size.height / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[size.width, size.height, size.depth]} />
        <meshStandardMaterial
          color={PALETTE.wall}
          roughness={0.34}
          metalness={0.22}
          envMapIntensity={0.9}
        />
      </mesh>

      {/* Roof slab, proud of the walls so the mass reads as a building */}
      <mesh position={[0, size.height + 0.05, 0]} castShadow receiveShadow>
        <boxGeometry args={[size.width + 0.16, 0.1, size.depth + 0.16]} />
        <meshStandardMaterial color={PALETTE.roof} roughness={0.72} metalness={0.1} />
      </mesh>

      {/* A banding stripe, which is what stops a big box looking like a box */}
      <mesh position={[0, size.height * 0.82, 0]}>
        <boxGeometry args={[size.width + 0.02, 0.05, size.depth + 0.02]} />
        <meshStandardMaterial color={PALETTE.trim} roughness={0.5} metalness={0.25} />
      </mesh>

      <DockFace width={size.width} depth={size.depth} height={size.height} />
      <RoofPlant width={size.width} depth={size.depth} height={size.height} />
      <OfficeAnnex
        position={[-size.width / 2 - 0.95, 0, size.depth * 0.16]}
        height={size.height}
      />
      <Silos position={[size.width / 2 + 1.15, 0, -size.depth * 0.1]} />

      {vans.map((van, i) => (
        <Van key={i} position={van.position} rotation={van.rotation} />
      ))}
      {trees.map((tree, i) => (
        <Tree key={i} position={tree.position} scale={tree.scale} />
      ))}

      <CapacityRing radius={ringRadius} utilisation={fill} />
      {warehouse.out_lines > 0 && <Marker height={size.height} />}

      {/* Label. HTML rather than extruded text: crisp at every zoom, uses the
          page's real typeface, and readable by a screen reader. */}
      <Html
        position={[0, size.height + (warehouse.out_lines > 0 ? 1.75 : 0.75), 0]}
        center
        distanceFactor={12}
        zIndexRange={[20, 0]}
      >
        <div className="pointer-events-none flex items-center gap-2 rounded-full border border-border bg-surface/95 px-3.5 py-2 shadow-md backdrop-blur-sm">
          <span className="font-display text-[14px] font-bold whitespace-nowrap text-ink">
            {warehouse.name}
          </span>
          <span className="tnum rounded-full bg-capacity-soft px-2 py-0.5 text-[12px] font-bold text-capacity">
            {warehouse.utilisation != null
              ? `${Math.round(warehouse.utilisation * 100)}%`
              : "—"}
          </span>
        </div>
      </Html>
    </group>
  );
}

/* ------------------------------------------------------------------ */
/* Transition                                                          */
/* ------------------------------------------------------------------ */

/**
 * Swaps one building for the next.
 *
 * The outgoing site slides and sinks away, the data changes at the midpoint
 * where nothing is visible, and the incoming one rises from the opposite side.
 * Driven by scale and position rather than opacity: fading thirty meshes means
 * marking every material transparent, which reorders how they sort against each
 * other and produces exactly the kind of flicker this animation exists to
 * avoid.
 */
function Stage({
  warehouse,
  largest,
  direction,
}: {
  warehouse: SiteWarehouse;
  largest: number;
  direction: number;
}) {
  const group = useRef<Group>(null);
  const [shown, setShown] = useState(warehouse);
  const phase = useRef(1); // 1 = settled, counts 0 -> 1 during a swap
  const pending = useRef<SiteWarehouse | null>(null);

  useEffect(() => {
    if (warehouse.id !== shown.id) {
      pending.current = warehouse;
      phase.current = 0;
    }
  }, [warehouse, shown.id]);

  useFrame((_, delta) => {
    if (!group.current) return;

    if (phase.current < 1) {
      phase.current = Math.min(1, phase.current + delta * 1.6);
      const t = phase.current;

      // Swap the data at the midpoint, while the building is out of frame.
      if (t >= 0.5 && pending.current) {
        setShown(pending.current);
        pending.current = null;
      }

      // Two halves of one arc: away, then back from the other side.
      const away = t < 0.5 ? t / 0.5 : 1 - (t - 0.5) / 0.5;
      const side = t < 0.5 ? direction : -direction;
      const eased = away * away * (3 - 2 * away); // smoothstep

      group.current.position.x = side * eased * 9;
      group.current.position.y = -eased * 1.6;
      group.current.scale.setScalar(1 - eased * 0.35);
    } else {
      group.current.position.x = 0;
      group.current.position.y = 0;
      group.current.scale.setScalar(1);
    }
  });

  return (
    <group ref={group}>
      <Warehouse warehouse={shown} largest={largest} />
    </group>
  );
}

/* ------------------------------------------------------------------ */
/* Scene                                                               */
/* ------------------------------------------------------------------ */

function Scene({
  warehouse,
  largest,
  direction,
}: {
  warehouse: SiteWarehouse;
  largest: number;
  direction: number;
}) {
  const key = useRef<DirectionalLight>(null);

  return (
    <>
      <ambientLight intensity={0.34} />
      <directionalLight
        ref={key}
        position={[6.5, 9, 5]}
        intensity={2.6}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0006}
        shadow-normalBias={0.02}
        shadow-camera-left={-14}
        shadow-camera-right={14}
        shadow-camera-top={14}
        shadow-camera-bottom={-14}
      />
      {/* Cool bounce from the opposite side, so shadowed faces stay blue rather
          than going muddy grey. */}
      <directionalLight position={[-7, 4, -5]} intensity={0.5} color="#a8bdea" />

      {/* Reflections without a network fetch. These emissive planes are what the
          walls and silos actually mirror. */}
      <Environment resolution={256} frames={1}>
        <Lightformer intensity={2.4} position={[0, 6, 2]} scale={[12, 6, 1]} />
        <Lightformer intensity={1.1} position={[-6, 3, -4]} scale={[8, 5, 1]} color="#dbe4fa" />
        <Lightformer intensity={0.9} position={[6, 2, 4]} scale={[8, 4, 1]} color="#ffffff" />
      </Environment>

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[70, 55]} />
        <meshStandardMaterial color={PALETTE.ground} roughness={1} />
      </mesh>

      <Stage warehouse={warehouse} largest={largest} direction={direction} />

      <ContactShadows
        position={[0, 0.018, 0]}
        opacity={0.62}
        scale={26}
        blur={1.7}
        far={6}
        color="#3d4d75"
      />
    </>
  );
}

export function SiteScene({
  warehouse,
  largest,
  direction,
}: {
  warehouse: SiteWarehouse;
  largest: number;
  direction: number;
}) {
  // Honoured rather than assumed: an orbiting camera is exactly the ambient
  // motion that makes some people ill.
  const stillness =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [7.2, 5.1, 8.6], fov: 32 }}
      gl={{ antialias: false }}
      style={{ touchAction: "none" }}
    >
      <color attach="background" args={["#eaeef8"]} />
      <fog attach="fog" args={["#eaeef8", 17, 34]} />

      {/* Selection wraps the scene so the ring and the marker can be the only
          things bloom touches. */}
      <Selection>
        <EffectComposer multisampling={0} enableNormalPass>
          <N8AO
            aoRadius={1.1}
            distanceFalloff={0.9}
            intensity={4.2}
            quality="medium"
            color="#54648c"
            halfRes
          />
          <SelectiveBloom
            intensity={2.2}
            luminanceThreshold={0.15}
            luminanceSmoothing={0.35}
            mipmapBlur
            radius={0.72}
          />
          {/* N8AO needs multisampling off, which takes MSAA with it. SMAA puts
              the edge quality back as a post pass — without it the silo
              cylinders and roof edges crawl. */}
          <SMAA />
        </EffectComposer>

        <Scene warehouse={warehouse} largest={largest} direction={direction} />
      </Selection>

      <OrbitControls
        makeDefault
        enablePan={false}
        autoRotate={!stillness}
        autoRotateSpeed={0.3}
        target={[0.35, 0.8, 0]}
        minPolarAngle={Math.PI / 7}
        // Stops short of the horizon: below this the apron fills the frame and
        // the building stops reading as a site.
        maxPolarAngle={Math.PI / 2.5}
        minDistance={6.5}
        maxDistance={17}
      />
    </Canvas>
  );
}

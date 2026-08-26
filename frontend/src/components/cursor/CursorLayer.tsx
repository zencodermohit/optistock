import { useEffect, useRef, useState } from "react";

/**
 * A cursor with physics.
 *
 * Three parts, each with a different job and a different amount of lag:
 *
 *   dot    follows exactly, no smoothing. This is the one that has to feel
 *          responsive -- lag on the precise point is what makes a custom
 *          cursor feel broken rather than fluid.
 *   ring   trails on a spring. All of the personality lives here.
 *   label  trails on a softer spring, so it settles after the ring and reads
 *          as being dragged along behind it.
 *
 * The whole layer is `pointer-events: none`, so nothing underneath ever loses
 * a click, and it renders into a fixed full-screen overlay above every other
 * z-index in the app.
 *
 * PERFORMANCE. React state is never touched on mousemove. Coordinates live in
 * refs and the animation loop writes `transform` straight onto the DOM nodes,
 * so a 60fps pointer causes zero re-renders. State changes only when the
 * cursor's KIND changes -- default to interactive to hidden -- which happens a
 * few times a second at worst.
 */

/* -------------------------------------------------------------------------- */
/* The spring                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * A damped harmonic oscillator, integrated with semi-implicit Euler.
 *
 *   a = -k(x - target) - c·v      Hooke's law, plus viscous damping
 *   v += a·dt
 *   x += v·dt                     (semi-implicit: uses the NEW v, which is
 *                                  what keeps it stable at large dt)
 *
 * TUNING:
 *   stiffness (k)  how hard it is pulled toward the target. Higher = snappier
 *                  and faster to arrive. 90 is lively; 300 is nearly instant.
 *   damping   (c)  how much the motion is resisted. Higher = less overshoot.
 *
 * The relationship between them is what actually matters. Critical damping —
 * the fastest approach with NO overshoot — is at c = 2·√k. Below that the
 * cursor springs past the pointer and swings back (bouncy, playful); above it
 * the cursor eases in and never overshoots (calm, expensive-feeling). The ring
 * below is set just under critical so it has a trace of overshoot on fast
 * flicks and none on small movements.
 *
 * Why a spring instead of the more common `x += (target - x) * 0.1` lerp: that
 * form is frame-rate dependent (it moves 10% per FRAME, so it is twice as fast
 * at 120Hz) and it has exactly one knob. A spring is time-correct and gives
 * you two independent controls, which is what makes it tunable at all.
 */
interface Spring {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

function stepSpring(
  s: Spring,
  targetX: number,
  targetY: number,
  stiffness: number,
  damping: number,
  dt: number,
) {
  const ax = -stiffness * (s.x - targetX) - damping * s.vx;
  const ay = -stiffness * (s.y - targetY) - damping * s.vy;
  s.vx += ax * dt;
  s.vy += ay * dt;
  s.x += s.vx * dt;
  s.y += s.vy * dt;
}

/* -------------------------------------------------------------------------- */
/* What the cursor is currently over                                           */
/* -------------------------------------------------------------------------- */

type Kind = "default" | "interactive" | "hidden";

/** Anything a click does something to. `[data-cursor="interactive"]` is the
 *  escape hatch for a custom control that is none of these. */
const INTERACTIVE =
  'a[href], button:not([disabled]), [role="button"], summary, ' +
  'input[type="checkbox"], input[type="radio"], label[for], ' +
  '[data-cursor="interactive"]';

/** Where the native cursor carries information we cannot replace. A caret
 *  tells you where the next character lands; a circle does not. */
const NATIVE = 'input:not([type="checkbox"]):not([type="radio"]), textarea, select, [contenteditable="true"]';

export function CursorLayer({ label }: { label?: string }) {
  const dot = useRef<HTMLDivElement>(null);
  const ring = useRef<HTMLDivElement>(null);
  const tag = useRef<HTMLDivElement>(null);

  const target = useRef({ x: -100, y: -100 });
  const ringSpring = useRef<Spring>({ x: -100, y: -100, vx: 0, vy: 0 });
  const tagSpring = useRef<Spring>({ x: -100, y: -100, vx: 0, vy: 0 });

  const [kind, setKind] = useState<Kind>("hidden");
  const kindRef = useRef<Kind>("hidden");

  /* -- Capability gate ---------------------------------------------------- */
  // A phone has no cursor to replace, and a person who asked for less motion
  // did not ask for a springy one. Both fall back to the native pointer.
  const [enabled] = useState(() => {
    if (typeof window === "undefined") return false;
    return (
      window.matchMedia("(pointer: fine)").matches &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  });

  /* -- Hide the native cursor, and always give it back -------------------- */
  useEffect(() => {
    if (!enabled) return;
    const root = document.documentElement;
    root.classList.add("cursor-custom");
    // The cleanup is the important half: a crash, a route change that unmounts
    // this, or a hot reload must not leave the user with no pointer at all.
    return () => root.classList.remove("cursor-custom");
  }, [enabled]);

  /* -- Track the pointer -------------------------------------------------- */
  useEffect(() => {
    if (!enabled) return;

    function setKindOnce(next: Kind) {
      if (kindRef.current === next) return;
      kindRef.current = next;
      setKind(next);
    }

    function onMove(event: PointerEvent) {
      target.current.x = event.clientX;
      target.current.y = event.clientY;

      const el = event.target as Element | null;
      if (!el || typeof el.closest !== "function") return;

      // Over a text field the custom cursor steps aside entirely and the CSS
      // hands the native I-beam back.
      if (el.closest(NATIVE)) setKindOnce("hidden");
      else if (el.closest(INTERACTIVE)) setKindOnce("interactive");
      else setKindOnce("default");
    }

    // Leaving the window restores the real cursor; re-entering takes it back.
    function onLeave() {
      setKindOnce("hidden");
    }
    function onEnter() {
      setKindOnce("default");
    }

    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    document.addEventListener("pointerenter", onEnter);
    // A drag that ends outside the window never fires pointermove again.
    window.addEventListener("blur", onLeave);

    return () => {
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("pointerenter", onEnter);
      window.removeEventListener("blur", onLeave);
    };
  }, [enabled]);

  /* -- The loop ----------------------------------------------------------- */
  useEffect(() => {
    if (!enabled) return;

    let frame = 0;
    let last = performance.now();

    function tick(now: number) {
      // Clamped. A backgrounded tab resumes with a dt of several seconds, and
      // an unclamped spring integrates that into a cursor flung off-screen.
      const dt = Math.min((now - last) / 1000, 1 / 30);
      last = now;

      const { x, y } = target.current;

      // Ring: just under critical damping (2·√220 ≈ 29.7), so fast flicks
      // overshoot slightly and small movements do not.
      stepSpring(ringSpring.current, x, y, 220, 26, dt);
      // Label: softer and heavier, so it settles after the ring.
      stepSpring(tagSpring.current, x, y, 120, 20, dt);

      // translate3d, not top/left: it is composited on the GPU and never
      // triggers layout or paint. Writing top/left here would thrash the whole
      // document on every frame.
      if (dot.current) {
        dot.current.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`;
      }
      if (ring.current) {
        const r = ringSpring.current;
        ring.current.style.transform = `translate3d(${r.x}px, ${r.y}px, 0) translate(-50%, -50%)`;
      }
      if (tag.current) {
        const t = tagSpring.current;
        tag.current.style.transform = `translate3d(${t.x}px, ${t.y}px, 0)`;
      }

      frame = requestAnimationFrame(tick);
    }

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [enabled]);

  if (!enabled) return null;

  const visible = kind !== "hidden";
  const active = kind === "interactive";

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-[9999] overflow-hidden"
    >
      {/* The ring — the part with the physics. */}
      <div
        ref={ring}
        className={[
          "absolute top-0 left-0 rounded-full border-2 will-change-transform",
          "transition-[width,height,background-color,border-color,opacity] duration-200 ease-out",
          active
            ? "h-10 w-10 border-accent bg-accent/12"
            : "h-7 w-7 border-accent/45 bg-transparent",
          visible ? "opacity-100" : "opacity-0",
        ].join(" ")}
      />

      {/* The dot — exact, so the cursor still feels precise. */}
      <div
        ref={dot}
        className={[
          "absolute top-0 left-0 rounded-full bg-accent will-change-transform",
          "transition-[width,height,opacity] duration-200 ease-out",
          active ? "h-1 w-1" : "h-1.5 w-1.5",
          visible ? "opacity-100" : "opacity-0",
        ].join(" ")}
      />

      {/* The label — the collaborative-cursor look, and the same component the
          remote cursors use. */}
      {label && (
        <div
          ref={tag}
          className={[
            "absolute top-0 left-0 will-change-transform",
            "transition-opacity duration-200",
            visible ? "opacity-100" : "opacity-0",
          ].join(" ")}
        >
          <span className="ml-4 mt-4 inline-block rounded-full bg-accent px-2.5 py-1 font-display text-2xs font-bold whitespace-nowrap text-on-accent shadow-md">
            {label}
          </span>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Remote cursors                                                              */
/* -------------------------------------------------------------------------- */

export interface RemotePointer {
  id: string;
  name: string;
  /** Viewport-relative, 0–1. Never pixels — see the note in the component. */
  x: number;
  y: number;
  colour: string;
}

/**
 * Somebody else's cursor.
 *
 * Positions arrive NORMALISED (0–1) rather than in pixels, because the sender
 * and receiver do not share a viewport size. Broadcasting raw clientX from a
 * 2560px monitor puts the cursor off the right edge of a laptop; a fraction of
 * the viewport lands in the same relative place on both.
 *
 * The spring is deliberately softer than the local one. Remote updates arrive
 * throttled — 20–30 a second at best, fewer over a bad connection — and a stiff
 * spring makes that arrive as visible stepping. A loose spring reads the gaps
 * as smooth motion, which is the whole trick behind multiplayer cursors feeling
 * live.
 */
export function RemoteCursor({ pointer }: { pointer: RemotePointer }) {
  const node = useRef<HTMLDivElement>(null);
  const spring = useRef<Spring>({ x: 0, y: 0, vx: 0, vy: 0 });
  const target = useRef({ x: 0, y: 0 });

  target.current = {
    x: pointer.x * window.innerWidth,
    y: pointer.y * window.innerHeight,
  };

  useEffect(() => {
    let frame = 0;
    let last = performance.now();

    function tick(now: number) {
      const dt = Math.min((now - last) / 1000, 1 / 30);
      last = now;
      // Softer than the local cursor: 90/18 against 220/26.
      stepSpring(spring.current, target.current.x, target.current.y, 90, 18, dt);
      if (node.current) {
        const s = spring.current;
        node.current.style.transform = `translate3d(${s.x}px, ${s.y}px, 0)`;
      }
      frame = requestAnimationFrame(tick);
    }

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div
      ref={node}
      aria-hidden
      className="pointer-events-none fixed top-0 left-0 z-[9998] will-change-transform"
    >
      <svg width="20" height="22" viewBox="0 0 20 22" fill="none">
        <path
          d="M2 1.5 L2 17 L6.4 13.2 L9.1 19.6 L12 18.3 L9.3 12.1 L15 12 Z"
          fill={pointer.colour}
          stroke="white"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
      </svg>
      <span
        className="ml-3.5 inline-block rounded-full px-2.5 py-1 font-display text-2xs font-bold whitespace-nowrap text-white shadow-md"
        style={{ backgroundColor: pointer.colour }}
      >
        {pointer.name}
      </span>
    </div>
  );
}

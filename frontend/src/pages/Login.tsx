import {
  ArrowRight,
  Eye,
  EyeOff,
  Loader2,
  Lock,
  Mail,
  ShieldCheck,
  ShoppingCart,
  TrendingUp,
  Layers,
  Warehouse,
  RefreshCw,
  Truck,
  AlertTriangle,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { CubeWordmark } from "@/components/ui/CubeMark";
import { Input } from "@/components/ui/Input";
import { WarehouseScene } from "@/components/ui/WarehouseScene";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/**
 * The door.
 *
 * Two halves that do different jobs. The left is the only marketing surface in
 * the entire product and is allowed to argue; the right is a form and does
 * nothing but take two fields and a click. Below the lg breakpoint the argument
 * is dropped entirely rather than stacked — someone signing in on a phone wants
 * the form, not the pitch.
 *
 * ── REPLACING THE ILLUSTRATION ──────────────────────────────────────────────
 * `WarehouseScene` is an original stand-in so this page ships complete. To swap
 * in a licensed 3D render instead:
 *
 *   1. Save the file as  frontend/src/assets/warehouse-hero.png
 *   2. Uncomment the import below, and set HERO to it.
 *
 * Nothing else changes — the slot already handles sizing and placement, and the
 * scene falls back automatically if HERO is null.
 *
 * Do check the licence covers use in a deployed application. The reference this
 * page was designed from is Peter Tarka's work and is not ours to ship.
 */
// import heroImage from "@/assets/warehouse-hero.png";
const HERO: string | null = null;

/** What the product does, stated as verbs rather than features. */
const CAPABILITIES = [
  { icon: ShieldCheck, lines: ["Prevent", "Stockouts"] },
  { icon: Layers, lines: ["Reduce", "Holding Costs"] },
  { icon: ShoppingCart, lines: ["Optimize", "Procurement"] },
  { icon: TrendingUp, lines: ["Improve", "Efficiency"] },
];

/**
 * Illustrative, and labelled as such further down the panel.
 *
 * These cannot be live. Nobody is signed in yet, so there is no company to
 * report on and no token to fetch it with — and an endpoint that served real
 * stock positions to an unauthenticated visitor would be a data leak, not a
 * nice touch. Representative figures on a marketing panel are ordinary; the
 * only thing that would be dishonest is presenting them as somebody's actual
 * numbers, so the panel says plainly that they are a sample.
 */
const NETWORK = [
  { city: "Nagpur", level: "97.1%", top: "20%", left: "0%", node: [15, 30] },
  { city: "Pune", level: "98.2%", top: "2%", left: "66%", node: [68, 14] },
  { city: "Mumbai", level: "99.4%", top: "64%", left: "2%", node: [17, 76] },
  { city: "Delhi", level: "96.8%", top: "56%", left: "72%", node: [72, 68] },
];

/**
 * The links between the sites, drawn behind the scene.
 *
 * `vector-effect="non-scaling-stroke"` is what makes this work at any panel
 * width: the viewBox is stretched to fill the container, and without it both
 * the stroke weight and the dash rhythm would stretch with it — thick, sparse
 * dashes on a wide screen and a hairline on a narrow one.
 */
function NetworkLinks() {
  // A ring, not a star. Spokes into a central hub were the obvious reading of
  // the reference and the wrong one: the warehouse sits at the centre of this
  // panel, so every spoke disappeared behind the platform and only the stubs
  // near the cards survived. Routing the link around the OUTSIDE keeps the
  // whole path visible and says the truer thing anyway — these four sites
  // trade with each other, they do not all report to a middle.
  const ring = [
    "M15,30 Q40,6 68,14", // Nagpur → Pune, over the top
    "M68,14 Q88,38 72,68", // Pune → Delhi, down the right
    "M72,68 Q46,92 17,76", // Delhi → Mumbai, under the floor
    "M17,76 Q1,52 15,30", // Mumbai → Nagpur, up the left
  ];

  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="absolute inset-0 h-full w-full"
      aria-hidden
    >
      {ring.map((d) => (
        <path
          key={d}
          d={d}
          fill="none"
          stroke="var(--color-night-accent)"
          strokeWidth="1.25"
          strokeDasharray="1 6"
          strokeLinecap="round"
          opacity="0.5"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

/**
 * The lit node at each site.
 *
 * HTML rather than another SVG circle, and that is not a style preference.
 * `preserveAspectRatio="none"` is what lets the ring above line up with cards
 * positioned in percentages, but it stretches geometry as well as coordinates —
 * `vector-effect` rescues the strokes and does nothing for a fill, so every
 * circle came out an ellipse. A div with `rounded-full` cannot be stretched by
 * a viewBox.
 */
function NetworkNodes() {
  return (
    <>
      {NETWORK.map(({ city, node }) => (
        <span
          key={city}
          aria-hidden
          className="absolute -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${node[0]}%`, top: `${node[1]}%` }}
        >
          <span className="bg-night-accent/20 block h-4 w-4 rounded-full p-1">
            <span className="bg-night-accent block h-2 w-2 rounded-full" />
          </span>
        </span>
      ))}
    </>
  );
}

const STATUS = [
  { icon: Warehouse, value: "5", lines: ["Warehouses", "Connected"] },
  { icon: RefreshCw, value: "12", lines: ["Active", "Transfers"] },
  { icon: Truck, value: "18", lines: ["Orders", "In Transit"] },
  { icon: AlertTriangle, value: "2", lines: ["Critical", "Alerts"], alert: true },
];

export function Login() {
  const { signIn, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("admin@technova.com");
  const [password, setPassword] = useState("Demo@12345");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (isAuthenticated) return <Navigate to="/" replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signIn(email, password);
      // Send them back where they were headed before being bounced to login.
      const to = (location.state as { from?: string })?.from ?? "/";
      navigate(to, { replace: true });
    } catch (err) {
      // The backend deliberately returns the same message for a wrong password
      // and an unknown address, so an attacker can't enumerate accounts. Pass
      // it through verbatim rather than inventing a more "helpful" one.
      setError(
        err instanceof ApiError ? err.message : "Sign in failed. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.15fr_1fr]">
      {/* ================================================================== */}
      {/* The argument                                                        */}
      {/* ================================================================== */}
      <div className="bg-night relative hidden overflow-hidden lg:block">
        {/* Ground: a flat navy, a cool glow behind the scene, and a faint grid
            so the panel reads as a surveyed network rather than a gradient. */}
        <div
          aria-hidden
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(120% 90% at 62% 58%, #14204a 0%, #0a1128 40%, transparent 70%), " +
              "radial-gradient(80% 60% at 12% 8%, #16225090 0%, transparent 60%)",
          }}
        />
        <div
          aria-hidden
          className="absolute inset-0 opacity-[0.35]"
          style={{
            backgroundImage:
              "linear-gradient(var(--color-night-border-soft) 1px, transparent 1px), " +
              "linear-gradient(90deg, var(--color-night-border-soft) 1px, transparent 1px)",
            backgroundSize: "56px 56px",
            maskImage: "radial-gradient(80% 70% at 50% 45%, #000 30%, transparent 78%)",
          }}
        />

        <div className="relative flex h-full flex-col justify-between p-9 xl:p-12">
          <header>
            <CubeWordmark size={34} tone="night" />

            <h1 className="text-night-ink mt-9 text-[2.6rem] leading-[1.12] font-bold tracking-tight text-balance xl:text-5xl">
              Inventory Intelligence
              <br />
              for <span className="text-night-accent">Modern Warehouses</span>
            </h1>

            <p className="text-night-ink-muted mt-4 max-w-md text-lg leading-relaxed">
              Real-time insights. Smarter decisions.
              <br />
              Better inventory outcomes.
            </p>

            {/* Four capabilities, divided rather than boxed. A rule between
                items is lighter than four cards and keeps the eye moving. */}
            <ul className="mt-7 flex flex-wrap items-center gap-x-5 gap-y-4">
              {CAPABILITIES.map(({ icon: Icon, lines }, i) => (
                <li
                  key={lines.join(" ")}
                  className={
                    "flex items-center gap-2.5 " +
                    (i > 0 ? "border-night-border xl:border-l xl:pl-5" : "")
                  }
                >
                  <Icon className="text-night-accent h-5 w-5 shrink-0" />
                  <span className="text-night-ink text-sm leading-tight font-medium">
                    {lines[0]}
                    <br />
                    <span className="text-night-ink-muted">{lines[1]}</span>
                  </span>
                </li>
              ))}
            </ul>
          </header>

          {/* ---- The scene, with the network floating around it ---------- */}
          <div className="relative my-4 min-h-[19rem] flex-1">
            <NetworkLinks />

            <div className="absolute inset-0 flex items-center justify-center">
              {HERO ? (
                <img
                  src={HERO}
                  alt="A warehouse being loaded, illustrated."
                  className="max-h-full max-w-full object-contain"
                />
              ) : (
                <WarehouseScene className="h-full w-full" />
              )}
            </div>

            <NetworkNodes />

            {NETWORK.map(({ city, level, top, left }) => (
              <div
                key={city}
                className="bg-night-raised/85 border-night-border absolute rounded-xl border px-3.5 py-2.5 shadow-lg backdrop-blur-sm"
                style={{ top, left }}
              >
                <p className="text-night-ink text-sm font-semibold">{city}</p>
                <p className="text-night-ink-muted mt-1 flex items-center gap-1.5 text-xs">
                  <span className="bg-night-success h-1.5 w-1.5 rounded-full" />
                  In Stock
                </p>
                <p className="tnum text-night-success mt-0.5 text-sm font-medium">
                  {level}
                </p>
              </div>
            ))}
          </div>

          {/* ---- Status bar --------------------------------------------- */}
          <footer className="border-night-border bg-night-raised/70 rounded-2xl border p-5 backdrop-blur-sm">
            <div className="mb-4 flex items-center justify-between gap-4">
              <p className="text-night-ink text-base font-semibold">
                Today's Network Status
              </p>
              <p className="text-night-success flex items-center gap-1.5 text-xs font-medium">
                <span className="bg-night-success h-1.5 w-1.5 rounded-full" />
                All Systems Operational
              </p>
            </div>

            <ul className="grid grid-cols-4">
              {STATUS.map(({ icon: Icon, value, lines, alert }, i) => (
                <li
                  key={lines.join(" ")}
                  className={
                    "flex items-center gap-3 " +
                    (i > 0 ? "border-night-border border-l pl-4" : "")
                  }
                >
                  <Icon
                    className={
                      "h-6 w-6 shrink-0 " +
                      (alert ? "text-night-danger" : "text-night-accent")
                    }
                  />
                  <span>
                    <span className="tnum text-night-ink block text-2xl leading-none font-bold">
                      {value}
                    </span>
                    <span className="text-night-ink-muted mt-1 block text-2xs leading-tight">
                      {lines[0]}
                      <br />
                      {lines[1]}
                    </span>
                  </span>
                </li>
              ))}
            </ul>

            {/* Said once, quietly, rather than an asterisk on every figure. */}
            <p className="text-night-ink-subtle mt-4 text-2xs">
              Sample figures. Your workspace loads its own on sign-in.
            </p>
          </footer>
        </div>
      </div>

      {/* ================================================================== */}
      {/* The form                                                            */}
      {/* ================================================================== */}
      <div className="relative flex items-center justify-center overflow-hidden bg-canvas px-6 py-12">
        {/* Two whispers of texture so the panel isn't a flat fill: a dot field
            top-right, and a soft accent bloom bottom-left. */}
        <div
          aria-hidden
          className="absolute -top-10 -right-10 h-72 w-72 opacity-60"
          style={{
            backgroundImage: "radial-gradient(var(--color-border-strong) 1px, transparent 1px)",
            backgroundSize: "16px 16px",
            maskImage: "radial-gradient(closest-side, #000, transparent)",
          }}
        />
        <div
          aria-hidden
          className="absolute -bottom-24 -left-24 h-96 w-96 rounded-full opacity-50"
          style={{
            background:
              "radial-gradient(circle, var(--color-accent-soft) 0%, transparent 70%)",
          }}
        />

        <div className="relative w-full max-w-md rounded-2xl border border-border bg-surface p-8 shadow-lg sm:p-10">
          <CubeWordmark size={38} />
          <p className="mt-2.5 text-base text-ink-muted">
            Inventory Intelligence Platform
          </p>

          <h2 className="mt-9 text-3xl leading-tight font-bold tracking-tight">
            Welcome back!
          </h2>
          <p className="mt-1.5 text-base text-ink-muted">
            Sign in to continue to your dashboard
          </p>

          <form onSubmit={handleSubmit} className="mt-8 space-y-5" noValidate>
            <Input
              label="Email address"
              type="email"
              autoComplete="username"
              placeholder="Enter your email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              icon={<Mail className="h-4 w-4" />}
              className="h-12"
            />

            <Input
              label="Password"
              type={reveal ? "text" : "password"}
              autoComplete="current-password"
              placeholder="Enter your password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              icon={<Lock className="h-4 w-4" />}
              className="h-12"
              trailing={
                <button
                  type="button"
                  onClick={() => setReveal((v) => !v)}
                  // The control's name is what it will DO, not what it shows.
                  aria-label={reveal ? "Hide password" : "Show password"}
                  aria-pressed={reveal}
                  className="rounded-md p-1.5 text-ink-subtle transition-colors hover:text-ink"
                >
                  {reveal ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              }
            />

            {error && (
              <div
                role="alert"
                className="rounded-md border border-danger/20 bg-danger-soft px-3 py-2.5 text-sm text-danger"
              >
                {error}
              </div>
            )}

            <Button
              type="submit"
              className="h-12 w-full text-base"
              loading={submitting}
              icon={!submitting ? <ArrowRight className="order-2 h-4 w-4" /> : undefined}
            >
              {submitting ? "Signing in" : "Sign In"}
            </Button>
          </form>

          {/* No account self-service: accounts are provisioned by an admin
              inside a company, so there is nothing for a visitor to sign up to. */}
          <p className="mt-8 border-t border-border pt-6 text-sm text-ink-muted">
            Don't have an account?{" "}
            <span className="font-medium text-ink">Contact your administrator</span>
          </p>

          <p className="mt-4 text-xs text-ink-subtle">
            Demo workspace — seeded with four years of simulated trading data.
            <br />
            <span className="tnum">admin@technova.com</span> ·{" "}
            <span className="tnum">Demo@12345</span>
          </p>
        </div>
      </div>
    </div>
  );
}

/** Full-page spinner for the brief moment before we know who is signed in. */
export function AuthLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-ink-subtle" />
    </div>
  );
}

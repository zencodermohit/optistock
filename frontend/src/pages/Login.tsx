import { Loader2, Lock, Mail } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { StockMark } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Mark } from "@/components/ui/Mark";
import { Trace } from "@/components/ui/Trace";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function Login() {
  const { signIn, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("admin@technova.com");
  const [password, setPassword] = useState("Demo@12345");
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
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Form */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-9">
            <div className="mb-6 flex items-center gap-2.5">
              <Mark size={22} />
              <span className="font-display text-xl font-semibold">OptiStock</span>
            </div>
            <h1 className="text-3xl leading-tight font-semibold">Welcome back</h1>
            <p className="mt-2 text-base text-ink-muted">
              Sign in to your inventory workspace.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <Input
              label="Email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              icon={<Mail className="h-4 w-4" />}
            />
            <Input
              label="Password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              icon={<Lock className="h-4 w-4" />}
            />

            {error && (
              <div
                role="alert"
                className="rounded-md border border-danger/20 bg-danger-soft px-3 py-2.5 text-sm text-danger"
              >
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" size="lg" loading={submitting}>
              {submitting ? "Signing in" : "Sign in"}
            </Button>
          </form>

          <p className="mt-8 text-xs text-ink-subtle">
            Demo workspace — seeded with a year of simulated trading data.
            <br />
            <span className="tnum">admin@technova.com</span> ·{" "}
            <span className="tnum">Demo@12345</span>
          </p>
        </div>
      </div>

      {/* A specimen of the thing itself, rather than a claim about it. Hidden on
          small screens: the form is the job here, this is the argument. */}
      <div className="relative hidden overflow-hidden bg-sunken lg:block">
        <div className="absolute inset-0 flex flex-col justify-center">
          <figure className="ml-14">
            <figcaption className="mb-5 max-w-sm">
              <p className="eyebrow">Stock on hand · Warehouse BLR-01</p>
              <p className="mt-3 font-display text-2xl leading-snug font-semibold text-balance">
                A line converging on its reorder rule is visible days before the
                alert fires.
              </p>
            </figcaption>

            {/* Bleeds off the right edge: this is a fragment of a continuous
                sheet, not a card that happens to contain a table. */}
            <div className="-mr-px overflow-hidden rounded-l-lg border border-r-0 border-border bg-surface">
              <table className="w-full border-collapse text-sm">
                <tbody className="zebra">
                  {SPECIMEN.map((row) => {
                    const now = row.series[row.series.length - 1];
                    const low = now <= row.reorderPoint;
                    return (
                      <tr key={row.sku}>
                        <td className="tnum py-1.5 pl-4 text-2xs text-ink-subtle">
                          {row.sku}
                        </td>
                        <td className="max-w-[13rem] truncate px-3 py-1.5">
                          {row.name}
                        </td>
                        <td className="px-3 py-1.5">
                          <Trace
                            points={row.series}
                            reorderPoint={row.reorderPoint}
                            low={low}
                            label={`${row.name}, ${now} on hand`}
                          />
                        </td>
                        <td
                          className={cn(
                            "tnum px-3 py-1.5 text-right font-medium",
                            now === 0 && "text-danger",
                            low && now > 0 && "text-warning",
                          )}
                        >
                          {now.toLocaleString("en-IN")}
                        </td>
                        <td className="w-14 py-1.5 pr-4">
                          <StockMark quantity={now} reorderPoint={row.reorderPoint} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <p className="mt-5 max-w-sm text-xs text-ink-muted">
              Inventory intelligence for multi-warehouse operations. Sample rows
              shown; your workspace loads a year of trading data.
            </p>
          </figure>
        </div>
      </div>
    </div>
  );
}

/** Illustrative rows for the sign-in specimen. Not fetched, and labelled as such. */
const SPECIMEN = [
  {
    sku: "NOVA-KB-114",
    name: "Mechanical keyboard, TKL",
    reorderPoint: 600,
    series: [980, 940, 905, 860, 830, 790, 742, 700, 655, 610, 570, 528],
  },
  {
    sku: "NOVA-MN-027",
    name: "27-inch IPS monitor",
    reorderPoint: 120,
    series: [312, 318, 306, 299, 311, 304, 296, 308, 301, 297, 305, 299],
  },
  {
    sku: "NOVA-CB-008",
    name: "USB-C cable, 2 m",
    reorderPoint: 200,
    series: [420, 360, 300, 255, 190, 140, 96, 60, 38, 20, 8, 0],
  },
  {
    sku: "NOVA-HS-052",
    name: "Wireless headset",
    reorderPoint: 100,
    series: [140, 168, 190, 215, 244, 266, 290, 318, 340, 366, 392, 415],
  },
  {
    sku: "NOVA-DK-311",
    name: "Standing desk frame",
    reorderPoint: 60,
    series: [88, 66, 44, 22, 210, 186, 160, 138, 112, 90, 66, 44],
  },
  {
    sku: "NOVA-SS-190",
    name: "NVMe SSD, 1 TB",
    reorderPoint: 400,
    series: [1204, 1188, 1210, 1176, 1192, 1165, 1180, 1158, 1171, 1149, 1160, 1142],
  },
  {
    sku: "NOVA-WC-045",
    name: "1080p webcam",
    reorderPoint: 130,
    series: [268, 252, 240, 226, 214, 201, 190, 178, 167, 155, 144, 132],
  },
];

/** Full-page spinner for the brief moment before we know who is signed in. */
export function AuthLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-ink-subtle" />
    </div>
  );
}

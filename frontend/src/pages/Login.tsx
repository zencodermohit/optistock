import { Loader2, Lock, Mail } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

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
            <div className="mb-6 flex items-center gap-2">
              <div className="h-6 w-6 rounded-md bg-accent" />
              <span className="font-display text-lg font-semibold tracking-tight">
                OptiStock
              </span>
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

      {/* Editorial panel. Hidden on small screens — it is atmosphere, not content. */}
      <div className="relative hidden overflow-hidden bg-sunken lg:block">
        <div className="absolute inset-0 flex flex-col justify-center px-14">
          <blockquote className="max-w-md">
            <p className="font-display text-3xl leading-snug font-medium text-balance">
              Every stock movement, every forecast, every recommendation —
              <span className="text-accent"> traceable to the evidence </span>
              that produced it.
            </p>
            <footer className="mt-8 text-sm text-ink-muted">
              Inventory intelligence for multi-warehouse operations
            </footer>
          </blockquote>

          <dl className="mt-14 grid grid-cols-3 gap-8 border-t border-border pt-8">
            {[
              ["200", "products tracked"],
              ["4", "warehouses"],
              ["18.5k", "sales analysed"],
            ].map(([value, label]) => (
              <div key={label}>
                <dt className="tnum text-2xl font-medium">{value}</dt>
                <dd className="mt-1 text-xs text-ink-muted">{label}</dd>
              </div>
            ))}
          </dl>
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

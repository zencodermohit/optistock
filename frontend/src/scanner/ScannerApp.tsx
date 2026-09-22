/**
 * The scanner shell: sign in, then scan.
 *
 * Its own login form rather than sending people to the dashboard to get a
 * token, because the dashboard is 2.2 MB and the whole reason this app exists
 * is that a phone should not have to download it. The form is a dozen lines
 * and it means the scanner never depends on the other bundle at all.
 */

import { LogOut, ScanLine } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { useAuth } from "@/lib/auth";
import { ScanSurface } from "@/scanner/ScanSurface";

export function ScannerApp() {
  const { isAuthenticated, session, signOut } = useAuth();

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="flex items-center gap-2 font-semibold">
          <ScanLine className="h-5 w-5 text-accent" />
          OptiStock Scanner
        </span>
        {isAuthenticated && (
          <button
            onClick={signOut}
            className="flex items-center gap-1.5 text-xs text-ink-muted"
          >
            <LogOut className="h-3.5 w-3.5" />
            {session?.email?.split("@")[0]}
          </button>
        )}
      </header>

      {isAuthenticated ? <ScanSurface /> : <SignIn />}
    </div>
  );
}

function SignIn() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(email, password);
    } catch (problem) {
      setError(
        problem instanceof Error ? problem.message : "Could not sign in."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto grid max-w-sm gap-3 p-6">
      <p className="text-sm text-ink-muted">
        Sign in with the account that will be recorded against every scan.
      </p>
      <input
        type="email"
        autoComplete="username"
        inputMode="email"
        placeholder="Email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        className="h-11 rounded-md border border-border-strong bg-surface px-3 text-ink"
      />
      <input
        type="password"
        autoComplete="current-password"
        placeholder="Password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        className="h-11 rounded-md border border-border-strong bg-surface px-3 text-ink"
      />
      {error && <p className="text-sm text-danger">{error}</p>}
      <Button type="submit" size="lg" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}

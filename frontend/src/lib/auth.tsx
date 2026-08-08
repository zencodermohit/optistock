/**
 * Who is signed in, and what they may do.
 *
 * The JWT is not encrypted — only signed — so the client can read its claims to
 * decide what to *show*. That is a UI convenience, never a security control:
 * hiding a button stops nobody from calling the endpoint. Every one of these
 * checks is enforced again server-side, which is the check that counts.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, setUnauthenticatedHandler, tokenStore } from "@/lib/api";

export interface Session {
  userId: string;
  companyId: string;
  role: string;
  email?: string;
  expiresAt: number;
}

interface AuthValue {
  session: Session | null;
  isAuthenticated: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  /** UI-level capability check. The server enforces the real one. */
  can: (...roles: string[]) => boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() =>
    decode(tokenStore.get()),
  );

  const signOut = useCallback(() => {
    tokenStore.clear();
    setSession(null);
  }, []);

  // The API layer calls this when the server rejects our token — expired, or
  // the user was deactivated since it was issued.
  useEffect(() => setUnauthenticatedHandler(signOut), [signOut]);

  const signIn = useCallback(async (email: string, password: string) => {
    const { access_token } = await api<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    tokenStore.set(access_token);
    const decoded = decode(access_token);
    if (!decoded) throw new Error("The server returned a token we can't read.");
    setSession({ ...decoded, email });
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      session,
      isAuthenticated: session !== null,
      signIn,
      signOut,
      can: (...roles) => (session ? roles.includes(session.role) : false),
    }),
    [session, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

/** Read the claims out of a JWT payload. Signature verification is the server's job. */
function decode(token: string | null): Session | null {
  if (!token) return null;
  try {
    const payload = JSON.parse(
      atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
    );
    // Treat an already-expired token as no session rather than letting every
    // request 401 its way to the same conclusion.
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      tokenStore.clear();
      return null;
    }
    return {
      userId: payload.sub,
      companyId: payload.company_id,
      role: payload.role,
      expiresAt: (payload.exp ?? 0) * 1000,
    };
  } catch {
    tokenStore.clear();
    return null;
  }
}

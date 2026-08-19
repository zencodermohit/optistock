/**
 * The one place the app talks to the backend.
 *
 * Every request goes through `api()`, which means the token header, error
 * normalisation and the 401 response all live in exactly one file. Scattering
 * `fetch` calls across components is how you end up with four different ways of
 * reading an error message and one endpoint that quietly forgot to authenticate.
 */

const TOKEN_KEY = "optistock.token";

/** Thrown for any non-2xx response, carrying the status so callers can branch. */
export class ApiError extends Error {
  // Declared and assigned explicitly rather than as constructor parameter
  // properties: `erasableSyntaxOnly` forbids TypeScript syntax that emits
  // runtime code, so the build can strip types instead of compiling them.
  status: number;
  detail?: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** True when the failure is worth retrying (server-side or transport). */
  get isRetryable() {
    return this.status === 0 || this.status >= 500 || this.status === 429;
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

/** Notified when the server rejects our token, so the app can send us to login. */
let onUnauthenticated: (() => void) | null = null;
export function setUnauthenticatedHandler(handler: () => void) {
  onUnauthenticated = handler;
}

type Options = Omit<RequestInit, "body"> & { body?: unknown };

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { body, headers, ...rest } = options;
  const token = tokenStore.get();

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...rest,
      headers: {
        ...(body !== undefined && { "Content-Type": "application/json" }),
        ...(token && { Authorization: `Bearer ${token}` }),
        ...headers,
      },
      ...(body !== undefined && { body: JSON.stringify(body) }),
    });
  } catch {
    // fetch only rejects on transport failure — server down, DNS, offline.
    throw new ApiError(0, "Cannot reach the server. Is the API running?");
  }

  if (response.status === 401) {
    // "Your session has expired" is only true if there WAS a session, and this
    // branch used to say it unconditionally. A sign-in request carries no
    // token, so a 401 there means the credentials were rejected -- and the
    // server already says so precisely ("Incorrect email or password",
    // "Inactive user"), uniformly enough not to reveal whether the address
    // exists. Overwriting that told a user whose account simply did not exist
    // that their session had expired, which is both false and the wrong thing
    // to act on: it sends you looking for an auth bug instead of a missing row.
    if (!token) {
      throw new ApiError(401, await readErrorMessage(response));
    }

    // A token was sent and refused: expired, or the user has since been
    // deactivated (the backend re-checks the live user on every request).
    // Now the message is accurate and clearing the token is the right move.
    tokenStore.clear();
    onUnauthenticated?.();
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/**
 * FastAPI reports errors in two shapes: `{detail: "message"}` for raised
 * HTTPExceptions, and `{detail: [{loc, msg, ...}]}` for validation failures.
 * Flatten both into something a human can read.
 */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;

    if (typeof detail === "string") return detail;

    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          const field = Array.isArray(item.loc) ? item.loc.at(-1) : null;
          return field ? `${field}: ${item.msg}` : item.msg;
        })
        .join(", ");
    }
  } catch {
    /* fall through to the generic message */
  }
  return `Request failed (${response.status})`;
}

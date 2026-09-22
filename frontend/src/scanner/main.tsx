/**
 * Bootstrap for the scanner, deliberately smaller than the dashboard's.
 *
 * No BrowserRouter: this app is one screen and has nowhere to navigate to.
 * No ThemeProvider either -- scanner.html stamps `data-theme` before the first
 * paint and the scanner offers no toggle, so the provider would ship a context
 * nothing reads.
 *
 * AuthProvider IS reused, and that is the point of keeping the same origin.
 * It reads and writes the same localStorage key as the dashboard, so a session
 * started in either one is a session in both, and `api()` attaches the token
 * here exactly as it does there.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ApiError } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import { ScannerApp } from "@/scanner/ScannerApp";
import "@/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) =>
        error instanceof ApiError
          ? error.isRetryable && failureCount < 2
          : failureCount < 2,
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
    mutations: {
      // A scan is never retried automatically. It is idempotent by
      // scan_reference, so a retry would be safe -- but it would also hide a
      // dead network from the person holding the phone, who needs to know
      // immediately that the last carton did not register.
      retry: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ScannerApp />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);

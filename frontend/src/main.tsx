import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "@/App";
import { ApiError } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import { ThemeProvider } from "@/lib/theme";
import "@/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retrying a 403 or a 404 just delays the error message. Only retry the
      // failures that might actually resolve themselves.
      retry: (failureCount, error) =>
        error instanceof ApiError
          ? error.isRetryable && failureCount < 2
          : failureCount < 2,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ThemeProvider>
            <App />
          </ThemeProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);

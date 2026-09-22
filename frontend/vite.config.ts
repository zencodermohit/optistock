import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // "@/components/..." rather than "../../../components/..."
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    rollupOptions: {
      // TWO APPS, ONE ORIGIN.
      //
      // The dashboard is 2.2 MB: three.js, a postprocessing pipeline, a chart
      // library, a markdown renderer. All of it earns its place on a desk and
      // none of it earns its place on a phone held over a carton, where the
      // job is to read a barcode and post three fields.
      //
      // A separate entry rather than a separate SITE, which is the part worth
      // keeping straight. Same origin means the scanner shares localStorage
      // with the dashboard, so it shares the token; it needs no CORS policy,
      // no second certificate and no second deployment. What it gets is its
      // own bundle and its own full-screen UI, which is all that was actually
      // wrong with serving it as a route.
      input: {
        main: path.resolve(__dirname, "index.html"),
        scanner: path.resolve(__dirname, "scanner.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Proxying means the browser only ever talks to one origin in dev, so
      // CORS never enters the picture. In production the two are served from
      // the same host behind Nginx, which has the same effect.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});

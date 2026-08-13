import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Host-based dev is the workflow: Vite runs on the host and the API is reachable at
// localhost:8000 (compose maps 8000:8000). The compose-internal name `api:8000` only
// resolves inside the compose network, so it cannot be the host default. Override with
// VITE_API_PROXY_TARGET when running Vite inside compose.
const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // Same-origin in dev: the app calls /api/* and Vite forwards to the API, so no CORS.
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API to the local FastAPI process. In normal use there is no dev
// server at all: `resumaid serve` mounts the built output and everything is one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});

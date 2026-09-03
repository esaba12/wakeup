import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// React + TypeScript + Vite, built to static assets and served by the
// openrestore daemon (see src/openrestore/app.py's static mount). No SSR,
// no backend framework of its own — docs/08-web-ui.md.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  server: {
    proxy: {
      // Local dev convenience: `npm run dev` proxies API calls to a
      // daemon started separately (`openrestore serve --mock-light
      // --mock-audio`), matching CLAUDE.md's --mock-light/--mock-audio
      // laptop workflow. Not used in the production build.
      "/api": {
        target: "http://127.0.0.1:8080",
        ws: true,
      },
    },
  },
});

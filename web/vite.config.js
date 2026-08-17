import { defineConfig } from "vite";

// base: relative by default so the built site works from file:// and from a project
// page at /<repo>/ without rebuilding. Override with BASE_URL when a deploy needs an
// absolute path (GitHub Pages sets this in CI).
export default defineConfig({
  base: process.env.BASE_URL || "./",
  build: {
    // the payload is one ~220 KB JSON module; keep it in the entry chunk rather than
    // letting Rollup split it out, so the page has a single request path
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 1024,
    outDir: "dist",
    target: "es2020",
  },
  server: { open: true, port: 5173 },
});

/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Strikte CSP im Betrieb: keine Inline-Skripte, keine data:-Schriften, keine externen Quellen.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Schriften und Bilder nie als data:-URI einbetten (font-src 'self')
    assetsInlineLimit: 0,
    // Kein Inline-Polyfill für modulepreload
    modulePreload: { polyfill: false },
    sourcemap: false,
    target: "es2020",
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// No SSR, no hash routing. The same bundle is served by the API in prod and
// wrapped by Capacitor on mobile (VITE_API_URL points at the API there).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": "/src" } },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8010", changeOrigin: true },
      "/ws": { target: "ws://localhost:8010", ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router", "@tanstack/react-query", "zustand"],
        },
      },
    },
  },
});

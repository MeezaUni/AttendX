import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies /api to the FastAPI backend so the browser sees a single origin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8470", changeOrigin: false } },
  },
  build: { chunkSizeWarningLimit: 1200 },
});

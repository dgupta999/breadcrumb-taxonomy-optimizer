import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// In dev, /api is proxied to the FastAPI backend (uvicorn on :8000).
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: true } },
  },
});

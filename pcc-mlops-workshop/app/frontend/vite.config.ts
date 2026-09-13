import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI backend serves the built files from ./dist and mounts /assets.
// In dev, proxy /api to the local uvicorn server on :8000.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

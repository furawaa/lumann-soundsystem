import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies to the FastAPI process so the frontend can hot-reload
// against a server that is holding a loaded model.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8420", changeOrigin: true, ws: false },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});

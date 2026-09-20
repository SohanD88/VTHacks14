import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  if (process.env.VERCEL && !/^https:\/\/[^/]+\/api\/?$/.test(env.VITE_API_BASE_URL || "")) {
    throw new Error("Set VITE_API_BASE_URL to your public HTTPS backend URL ending in /api.");
  }
  const proxy = {
    "/api": {
      target: env.API_PROXY_TARGET || "http://127.0.0.1:8000",
      changeOrigin: true,
      ws: true,
    },
  };
  return {
    plugins: [react()],
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 5173, strictPort: true, proxy },
    build: {
      rollupOptions: { output: { manualChunks: { three: ["three"] } } },
    },
  };
});

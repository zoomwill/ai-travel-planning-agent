import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import { readFrontendConfig } from "./src/auth/config.ts";

export default defineConfig(({ mode }) => {
  readFrontendConfig({ ...loadEnv(mode, process.cwd(), "VITE_"), ...process.env }, process.env.VERCEL_ENV === "production");
  return {
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/ready": "http://127.0.0.1:8000",
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: true,
    exclude: ["tests/e2e/**", "node_modules/**", "dist/**"],
  },
  };
});

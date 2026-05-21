import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { cesiumEngine } from "vite-plugin-cesium-engine";
import path, { resolve } from "path";
import { realpathSync } from "fs";

const cesiumEngineAlias = resolve(
  realpathSync(resolve(__dirname, "node_modules/cesium")),
  "../@cesium/engine",
);

export default defineConfig({
  plugins: [react(), tailwindcss(), cesiumEngine()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@cesium/engine": cesiumEngineAlias,
    },
    dedupe: ["cesium", "@cesium/engine", "@cesium/widgets"],
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});

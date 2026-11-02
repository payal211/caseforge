import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const api = "http://localhost:8000"; // FastAPI during `npm run dev`
export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  build: { outDir: path.resolve(__dirname, "../caseforge/api/static"), emptyOutDir: true },
  server: { proxy: Object.fromEntries(["/cases", "/domains", "/demo", "/metrics", "/health"].map((p) => [p, api])) },
  test: { environment: "jsdom" },
});

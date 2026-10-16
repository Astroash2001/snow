import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "electron-vite";

// Default entries: src/main/index.ts, src/preload/index.ts, src/renderer/index.html.
// No "type": "module" in package.json, so main and preload build as CommonJS (sandboxed preload needs it).
export default defineConfig({
  main: {},
  preload: {},
  renderer: { plugins: [react(), tailwindcss()] },
});

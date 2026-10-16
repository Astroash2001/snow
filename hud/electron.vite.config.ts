import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "electron-vite";

// Production renderer CSP: only its own files, and the one loopback hub socket (T-01-09).
// Applied at build time only; the dev server needs inline scripts and its own websocket for HMR.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "font-src 'self' data:",
  "img-src 'self' data:",
  "connect-src ws://127.0.0.1:*",
].join("; ");

const cspMeta = {
  name: "snow-csp",
  apply: "build" as const,
  transformIndexHtml: () => [
    {
      tag: "meta",
      attrs: { "http-equiv": "Content-Security-Policy", content: CSP },
      injectTo: "head-prepend" as const,
    },
  ],
};

// Default entries: src/main/index.ts, src/preload/index.ts, src/renderer/index.html.
// No "type": "module" in package.json, so main and preload build as CommonJS (sandboxed preload needs it).
export default defineConfig({
  main: {},
  preload: {},
  renderer: { plugins: [react(), tailwindcss(), cspMeta] },
});

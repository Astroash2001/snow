import { defineConfig } from "@playwright/test";

// Each spec launches Electron itself (see e2e/smoke.spec.ts) so it can point it at its own mock hub.
export default defineConfig({
  testDir: "e2e",
  workers: 1,
  timeout: 30_000,
  reporter: "list",
});

import { defineConfig } from "@playwright/test";

// Each spec launches Electron itself (see e2e/smoke.spec.ts) so it can point it at its own mock hub.
export default defineConfig({
  testDir: "e2e",
  workers: 1,
  // The shared CI runner is slow and uneven (timing tests failed there, passed locally);
  // a retried pass is still reported as flaky.
  retries: process.env.CI ? 2 : 0,
  timeout: 30_000,
  reporter: "list",
});

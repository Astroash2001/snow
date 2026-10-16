import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startMockHub } from "./mockHub";

const hudDir = resolve(__dirname, "..");

test("dashboard shows the banner when the hub drops and recovers on a new port", async () => {
  const hub = await startMockHub({ script: [] });
  // Same handoff the real hub uses: <data dir>/run/hub.json, re-read on every connect attempt.
  const dataDir = mkdtempSync(join(tmpdir(), "snow-hud-e2e-"));
  mkdirSync(join(dataDir, "run"));
  const writeHubJson = () =>
    writeFileSync(
      join(dataDir, "run", "hub.json"),
      JSON.stringify({ port: hub.port, token: hub.token }),
    );
  writeHubJson();

  const { SNOW_HUB_URL: _url, SNOW_TOKEN: _token, ...env } = process.env;
  const app = await electron.launch({
    args: ["."],
    cwd: hudDir,
    env: { ...env, SNOW_DATA_DIR: dataDir },
  });
  try {
    const win = await app.firstWindow();
    const word = win.getByTestId("state-word");
    const banner = win.getByTestId("connection-banner");
    const status = win.getByRole("status");
    const wait = { timeout: 15_000 };

    await expect(word).toHaveText("Listening", wait);
    await expect(banner).toHaveCount(0);

    await hub.close();
    await expect(banner).toBeVisible(wait);
    await expect(banner).toContainText("Cannot reach Snow's core");
    await expect(banner).toContainText(
      "Reconnecting automatically. Mute is unavailable until the connection returns.",
    );
    await expect(word).toHaveText("Reconnecting");

    await hub.restart(); // new port; the HUD must pick it up from the rewritten hub.json
    writeHubJson();
    await expect(banner).toHaveCount(0, wait);
    await expect(status).toHaveText("Reconnected", wait);
    await expect(word).toHaveText("Listening", wait);
  } finally {
    await app.close();
    await hub.close();
    rmSync(dataDir, { recursive: true, force: true });
  }
});

test("renderer is locked down: CSP present, no navigation, no new windows", async () => {
  const hub = await startMockHub({ script: [] });
  const app = await electron.launch({
    args: ["."],
    cwd: hudDir,
    env: { ...process.env, SNOW_HUB_URL: hub.url, SNOW_TOKEN: hub.token },
  });
  try {
    const win = await app.firstWindow();
    await expect(win.getByTestId("state-word")).toHaveText("Listening");
    const csp = await win.evaluate(() =>
      document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute("content"),
    );
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("connect-src ws://127.0.0.1:*");

    const href = await win.evaluate(() => location.href);
    await win.evaluate(() => {
      location.href = "data:text/html,navigated";
      window.open("data:text/html,popup");
    });
    await win.waitForTimeout(500);
    expect(await win.evaluate(() => location.href)).toBe(href);
    expect(app.windows()).toHaveLength(1);
  } finally {
    await app.close();
    await hub.close();
  }
});

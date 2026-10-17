import { resolve } from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import type { EventsSchema } from "../src/generated/contracts";
import type { SnowTestHook } from "../src/renderer/src/orb/renderer";
import { startMockHub } from "./mockHub";

const hudDir = resolve(__dirname, "..");
type TestWindow = Window & { __snowTest?: SnowTestHook };

const STATES = ["thinking", "speaking", "listening", "sleeping", "muted"] as const;
const EVENTS = 200;
const FIRST_SEQ = 1000;
const STALL_MS = 150; // a frame gap longer than this is the host, not the orb

const presence = (seq: number, state: (typeof STATES)[number]): EventsSchema => ({
  kind: "event",
  event: {
    type: "presence.state",
    seq,
    source: "voice",
    ts_ns: seq,
    state,
    mode: "awake",
  },
});

test("orb paints a state change within the HUD-03 budget", async () => {
  test.setTimeout(90_000);
  const hub = await startMockHub({ script: [] });
  const app = await electron.launch({
    // The flags stop Chromium throttling this window to 1 fps when another window covers it, which
    // would measure the desktop instead of the orb. Test runs only; the shipped app is unchanged.
    args: [
      ".",
      "--disable-backgrounding-occluded-windows",
      "--disable-renderer-backgrounding",
      "--disable-features=CalculateNativeWinOcclusion",
    ],
    cwd: hudDir,
    env: {
      ...process.env,
      SNOW_HUB_URL: hub.url,
      SNOW_TOKEN: hub.token,
      SNOW_HUD_TEST: "1", // exposes window.__snowTest and the perf marks
    },
  });
  try {
    const win = await app.firstWindow();
    const csp: string[] = [];
    win.on("console", (m) => {
      if (m.text().includes("Content Security Policy")) csp.push(m.text());
    });
    await expect(win.getByTestId("state-word")).toHaveText("Listening", { timeout: 15_000 });
    const stats = () => win.evaluate(() => (window as TestWindow).__snowTest?.orbStats() ?? null);
    // Atlases for every state are built in idle time after start; wait for them so the first
    // events do not measure the one-off startup work.
    await expect.poll(async () => (await stats())?.atlases, { timeout: 15_000 }).toBe(5);

    // An independent rAF probe: if the host stops delivering frames (another window covers this one,
    // the machine stalls), the probe stalls too, and those events say nothing about the orb.
    await win.evaluate((stallMs) => {
      const w = window as unknown as {
        __stalls: { from: number; to: number }[];
        __vis: { t: number; v: string }[];
      };
      w.__stalls = [];
      w.__vis = [];
      document.addEventListener("visibilitychange", () =>
        w.__vis.push({ t: performance.now(), v: document.visibilityState }),
      );
      let last = performance.now();
      const tick = (now: number) => {
        if (now - last > stallMs) w.__stalls.push({ from: last, to: now });
        last = now;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }, STALL_MS);
    for (let i = 0; i < EVENTS; i++) {
      hub.send(presence(FIRST_SEQ + i, STATES[i % STATES.length]));
      await win.waitForTimeout(100);
    }
    const lastSeq = `paint:${FIRST_SEQ + EVENTS - 1}`;
    await expect
      .poll(() => win.evaluate((n) => performance.getEntriesByName(n).length, lastSeq), {
        timeout: 5_000,
      })
      .toBe(1);

    const marks = await win.evaluate(() =>
      performance.getEntriesByType("mark").map((m) => ({ name: m.name, t: m.startTime })),
    );
    const at = (prefix: string) =>
      new Map(
        marks
          .filter((m) => m.name.startsWith(prefix))
          .map((m) => [m.name.slice(prefix.length), m.t]),
      );
    const evt = at("evt:");
    const paint = at("paint:");
    const stalls = await win.evaluate(
      () => (window as unknown as { __stalls: { from: number; to: number }[] }).__stalls,
    );
    if (stalls.length > 0) {
      const vis = await win.evaluate(() => (window as unknown as { __vis: unknown[] }).__vis);
      const wins = await app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows().map((w) => ({
          visible: w.isVisible(),
          minimized: w.isMinimized(),
          focused: w.isFocused(),
        })),
      );
      console.log(
        `host frame stalls: ${stalls.length}; visibility changes: ${JSON.stringify(vis)}; windows: ${JSON.stringify(wins)}`,
      );
    }
    const latencies: number[] = [];
    let hostStalled = 0;
    for (let i = 0; i < EVENTS; i++) {
      const seq = String(FIRST_SEQ + i);
      const e = evt.get(seq) as number;
      const p = paint.get(seq) as number;
      expect(e, `evt mark for seq ${seq}`).toBeDefined();
      expect(p, `paint mark for seq ${seq}`).toBeDefined();
      if (stalls.some((st) => e < st.to && p > st.from)) hostStalled += 1;
      else latencies.push(p - e);
    }
    // Excluding stalled events must not be able to hide a broken orb: at most 10% may be dropped.
    expect(
      hostStalled,
      `events lost to host frame stalls: ${JSON.stringify(stalls)}`,
    ).toBeLessThanOrEqual(EVENTS * 0.1);
    latencies.sort((a, b) => a - b);
    const p95 = latencies[Math.ceil(latencies.length * 0.95) - 1];
    const max = latencies[latencies.length - 1];
    const median = latencies[Math.floor(latencies.length / 2)];
    const s = await stats();
    console.log(
      `orb event-to-paint over ${latencies.length} events (${hostStalled} excluded for host frame stalls): median ${median.toFixed(1)} ms, p95 ${p95.toFixed(1)} ms, max ${max.toFixed(1)} ms; avg draw ${s?.avgDrawMs.toFixed(2)} ms over ${s?.frames} frames`,
    );
    expect(p95).toBeLessThanOrEqual(50);
    expect(max).toBeLessThanOrEqual(100);
    expect(s?.frames ?? 0).toBeGreaterThan(50);
    expect(s?.avgDrawMs ?? 99).toBeLessThan(4);

    // The alert marker: a failing language-model role shows it, a recovered one clears it.
    expect((await stats())?.alert).toBe(false);
    const role = (status: "failing" | "active"): EventsSchema => ({
      kind: "event",
      event: { type: "health.role", role: "brain", source: "hub", ts_ns: 1, status },
    });
    hub.send(role("failing"));
    await expect.poll(async () => (await stats())?.alert).toBe(true);
    hub.send(role("active"));
    await expect.poll(async () => (await stats())?.alert).toBe(false);

    // The production CSP (style-src 'self') must not reject the canvas sizing.
    expect(csp).toEqual([]);
  } finally {
    await app.close();
    await hub.close();
  }
});

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  type ElectronApplication,
  _electron as electron,
  expect,
  type Page,
  test,
} from "@playwright/test";
import type { EventsSchema, Snapshot } from "../src/generated/contracts";
import type { SnowTestHook } from "../src/renderer/src/orb/renderer";
import { type MockHub, startMockHub } from "./mockHub";

const hudDir = resolve(__dirname, "..");
const base: Snapshot = JSON.parse(
  readFileSync(resolve(hudDir, "../contracts/samples/events.json"), "utf8"),
).snapshot.snapshot;

// Everything a test starts is closed afterwards, even when the test fails or times out: the mini
// window is always on top and must never be left floating on the screen.
const apps: ElectronApplication[] = [];
const hubs: MockHub[] = [];
test.afterEach(async () => {
  for (const app of apps.splice(0)) await app.close().catch(() => undefined);
  for (const hub of hubs.splice(0)) await hub.close().catch(() => undefined);
});

interface WinInfo {
  title: string;
  visible: boolean;
  onTop: boolean;
  focusable: boolean;
  bounds: { x: number; y: number; width: number; height: number };
}
interface Ctx {
  app: ElectronApplication;
  dash: Page;
  hub: MockHub;
  emit: (type: string, fields?: Record<string, unknown>) => void;
  windows: () => Promise<WinInfo[]>;
  ignoreCalls: () => Promise<unknown[][]>;
  closeDashboard: () => Promise<void>;
  openMini: () => Promise<Page>;
}

async function withHud(snapshot: Partial<Snapshot>, run: (ctx: Ctx) => Promise<void>) {
  const hub = await startMockHub({
    script: [],
    snapshot: { ...base, rows: [], subsystems: [], roles: [], ...snapshot },
  });
  hubs.push(hub);
  const app = await electron.launch({
    args: ["."],
    cwd: hudDir,
    env: {
      ...process.env,
      SNOW_HUB_URL: hub.url,
      SNOW_TOKEN: hub.token,
      SNOW_HUD_TEST: "1",
    },
  });
  apps.push(app);
  // The mini window is created on first need, so this wrapper is in place before it exists.
  await app.evaluate(({ BrowserWindow }) => {
    const g = globalThis as unknown as { __ignoreCalls: unknown[][] };
    g.__ignoreCalls = [];
    const proto = BrowserWindow.prototype as unknown as {
      setIgnoreMouseEvents: (...a: unknown[]) => void;
    };
    const original = proto.setIgnoreMouseEvents;
    proto.setIgnoreMouseEvents = function (this: unknown, ...args: unknown[]) {
      g.__ignoreCalls.push(args);
      return original.apply(this, args);
    };
  });
  const dash = await app.firstWindow();
  await expect(dash.getByTestId("state-word")).not.toHaveText("Reconnecting");

  let n = 0;
  const emit: Ctx["emit"] = (type, fields = {}) => {
    n += 1;
    hub.send({
      kind: "event",
      event: { type, source: "voice", seq: n, ts_ns: 1_760_000_000_000_000_000 + n, ...fields },
    } as unknown as EventsSchema);
  };
  const windows = () =>
    app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows().map((w) => ({
        title: w.getTitle(),
        visible: w.isVisible(),
        onTop: w.isAlwaysOnTop(),
        focusable: w.isFocusable(),
        bounds: w.getBounds(),
      })),
    );
  const closeDashboard = () =>
    app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()
        .find((w) => w.getTitle() === "Snow")
        ?.close();
    });
  const openMini = async () => {
    await closeDashboard();
    await expect
      .poll(async () => (await windows()).find((w) => w.title === "Snow mini")?.visible)
      .toBe(true);
    const pages = app.windows();
    for (const p of pages) if ((await p.title()) === "Snow mini") return p;
    throw new Error("mini page not found");
  };
  const ignoreCalls = () =>
    app.evaluate(() => (globalThis as unknown as { __ignoreCalls: unknown[][] }).__ignoreCalls);
  await run({ app, dash, hub, emit, windows, ignoreCalls, closeDashboard, openMini });
}

const orbStats = (page: Page) =>
  page.evaluate(() => (window as Window & { __snowTest?: SnowTestHook }).__snowTest?.orbStats());

const snapshotRequests = (hub: MockHub) =>
  hub.received.filter(
    (m) => (m as { command?: { type?: string } }).command?.type === "cmd.snapshot",
  );

const find = (list: WinInfo[], title: string) => list.find((w) => w.title === title);

test("closing the dashboard shows the mini orb, clicking the orb brings the dashboard back; never both", async () => {
  await withHud({ presence: "sleeping" }, async (c) => {
    // Only the dashboard exists at first: the mini window is created when it is first needed.
    // The dashboard shows itself on ready-to-show, which can land just after its page is up.
    await expect.poll(async () => find(await c.windows(), "Snow")?.visible).toBe(true);
    let list = await c.windows();
    expect(find(list, "Snow mini")).toBeUndefined();

    const mini = await c.openMini();
    list = await c.windows();
    const dash = find(list, "Snow");
    const win = find(list, "Snow mini");
    expect(dash?.visible).toBe(false);
    expect(win?.visible).toBe(true);
    expect(win?.onTop).toBe(true);
    expect(win?.focusable).toBe(false);
    expect(win?.bounds.width).toBe(320);
    expect(win?.bounds.height).toBe(56);
    // Top-right of the primary work area, 16 px from the top and right (2 px for display rounding).
    const work = await c.app.evaluate(({ screen }) => screen.getPrimaryDisplay().workArea);
    const b = win?.bounds ?? { x: 0, y: 0, width: 0, height: 0 };
    expect(Math.abs(b.x + b.width - (work.x + work.width - 16))).toBeLessThanOrEqual(2);
    expect(Math.abs(b.y - (work.y + 16))).toBeLessThanOrEqual(2);

    // Click-through from the moment it exists.
    expect((await c.ignoreCalls())[0]).toEqual([true, { forward: true }]);
    // The orb is the 40 px orb, and it is the only thing in the idle window.
    await expect(mini.locator("canvas")).toHaveCount(1);
    expect(await mini.locator("canvas").evaluate((el) => (el as HTMLElement).style.width)).toBe(
      "40px",
    );
    await expect(mini.getByTestId("mini-caption")).toHaveCount(0);
    await expect(mini.getByTestId("mini-muted")).toHaveCount(0);

    // While hidden the dashboard renders nothing: no orb, no transcript, no health.
    await expect(c.dash.getByTestId("state-word")).toHaveCount(0);
    await expect(c.dash.locator("canvas")).toHaveCount(0);
    await expect(c.dash.getByTestId("transcript-log")).toHaveCount(0);
    expect(await orbStats(c.dash)).toBeNull();

    // Hover turns click-through off, leaving turns it back on.
    const orb = mini.getByTestId("mini-orb");
    await orb.hover();
    await expect.poll(async () => (await c.ignoreCalls()).at(-1)).toEqual([false]);
    await mini.mouse.move(2, 2);
    await expect
      .poll(async () => (await c.ignoreCalls()).at(-1))
      .toEqual([true, { forward: true }]);

    // Clicking the orb restores the dashboard, asks for a fresh snapshot and hides the mini.
    const before = snapshotRequests(c.hub).length;
    await orb.hover();
    await mini.getByRole("button", { name: /^Snow,/ }).click();
    await expect
      .poll(async () => {
        const l = await c.windows();
        return [find(l, "Snow")?.visible, find(l, "Snow mini")?.visible];
      })
      .toEqual([true, false]);
    await expect(c.dash.getByTestId("state-word")).toBeVisible();
    await expect.poll(() => snapshotRequests(c.hub).length).toBe(before + 1);
    // The mini goes back to click-through when it is hidden.
    expect((await c.ignoreCalls()).at(-1)).toEqual([true, { forward: true }]);

    // And minimizing does the same as closing.
    await c.app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()
        .find((w) => w.getTitle() === "Snow")
        ?.minimize();
    });
    await expect
      .poll(async () => {
        const l = await c.windows();
        return [find(l, "Snow")?.visible, find(l, "Snow mini")?.visible];
      })
      .toEqual([false, true]);
  });
});

test("the mini caption shows what Snow heard, updates in place, holds, then fades away", async () => {
  await withHud({ presence: "listening" }, async (c) => {
    const mini = await c.openMini();
    const caption = mini.getByTestId("mini-caption");
    await expect(caption).toHaveCount(0);

    c.emit("transcript.partial", { text: "open the", turn_id: "t1", seq: null });
    await expect(caption).toHaveText("open the");
    c.emit("transcript.partial", { text: "open the calendar", turn_id: "t1", seq: null });
    await expect(caption).toHaveText("open the calendar");
    expect(await caption.evaluate((el) => el.getBoundingClientRect().height)).toBe(32);

    c.emit("transcript.final", { text: "open the calendar please", turn_id: "t1" });
    await expect(caption).toHaveText("open the calendar please");
    // Still there well inside the 2.5 s hold, with a full opacity.
    await mini.waitForTimeout(1500);
    await expect(caption).toHaveText("open the calendar please");
    await expect(caption).toHaveAttribute("data-fading", "false");
    // Then it fades (400 ms) and leaves the DOM.
    await expect(caption).toHaveAttribute("data-fading", "true", { timeout: 3000 });
    await expect(caption).toHaveCount(0, { timeout: 3000 });

    // A long phrase stays on one line inside 256 px, the window does not resize.
    const long = "remind me tomorrow morning to send the quarterly report to the whole team";
    c.emit("transcript.partial", { text: long, turn_id: "t2", seq: null });
    await expect(caption).toHaveText(long);
    const box = await caption.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { w: r.width, h: r.height, lines: el.querySelectorAll("br").length };
    });
    expect(box.w).toBeLessThanOrEqual(256);
    expect(box.h).toBe(32);
    const win = find(await c.windows(), "Snow mini");
    expect([win?.bounds.width, win?.bounds.height]).toEqual([320, 56]);
    // Overflow turns the left mask on (the newest words stay visible).
    expect(
      await caption.evaluate((el) => getComputedStyle(el.firstElementChild as Element).maskImage),
    ).toContain("linear-gradient");

    // Never shown while sleeping.
    c.emit("presence.state", { state: "sleeping", mode: "awake" });
    await expect(caption).toHaveCount(0);
  });
});

test("hard mute shows a persistent Muted pill and the muted orb in the mini form", async () => {
  await withHud({ presence: "listening" }, async (c) => {
    const mini = await c.openMini();
    await expect(mini.getByTestId("mini-muted")).toHaveCount(0);
    c.emit("mute.changed", { muted: true, by: "voice" });
    c.emit("presence.state", { state: "muted", mode: "awake" });
    const pill = mini.getByTestId("mini-muted");
    await expect(pill).toHaveText("Muted");
    await expect.poll(async () => (await orbStats(mini))?.state).toBe("muted");
    // It does not fade.
    await mini.waitForTimeout(3200);
    await expect(pill).toBeVisible();
    // A caption never replaces it.
    c.emit("transcript.partial", { text: "hello", turn_id: "t1", seq: null });
    await mini.waitForTimeout(300);
    await expect(mini.getByTestId("mini-caption")).toHaveCount(0);
    await expect(pill).toBeVisible();

    c.emit("mute.changed", { muted: false, by: "hud" });
    await expect(pill).toHaveCount(0);
  });
});

test("a Down subsystem draws the alert dot on the mini orb until it is healthy", async () => {
  await withHud({ presence: "sleeping" }, async (c) => {
    const mini = await c.openMini();
    expect((await orbStats(mini))?.alert).toBe(false);
    const sub = (status: string) =>
      c.emit("health.subsystem", {
        name: "speech_to_text",
        label: "Speech to text",
        owner: "voice",
        status,
        detail: null,
      });
    sub("down");
    await expect.poll(async () => (await orbStats(mini))?.alert).toBe(true);
    sub("running");
    await expect.poll(async () => (await orbStats(mini))?.alert).toBe(false);
  });
});

test("until the first snapshot and after the socket drops the mini orb is offline and shows no caption", async () => {
  await withHud({ presence: "listening" }, async (c) => {
    const mini = await c.openMini();
    await expect.poll(async () => (await orbStats(mini))?.state).toBe("listening");
    c.emit("transcript.partial", { text: "hello there", turn_id: "t1", seq: null });
    await expect(mini.getByTestId("mini-caption")).toHaveText("hello there");

    await c.hub.close();
    await expect
      .poll(async () => (await orbStats(mini))?.state, { timeout: 15_000 })
      .toBe("offline");
    await expect(mini.getByTestId("mini-caption")).toHaveCount(0);
    await expect(mini.getByTestId("mini-muted")).toHaveCount(0);

    // Back online: the snapshot is the baseline, so it captions nothing by itself.
    await c.hub.restart(c.hub.port);
    await expect
      .poll(async () => (await orbStats(mini))?.state, { timeout: 15_000 })
      .toBe("listening");
    await expect(mini.getByTestId("mini-caption")).toHaveCount(0);
  });
});

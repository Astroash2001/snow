import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import {
  type ElectronApplication,
  _electron as electron,
  expect,
  type Page,
  test,
} from "@playwright/test";
import type { EventsSchema, Snapshot } from "../src/generated/contracts";
import { type MockHub, startMockHub } from "./mockHub";

const hudDir = resolve(__dirname, "..");
const base: Snapshot = JSON.parse(
  readFileSync(resolve(hudDir, "../contracts/samples/events.json"), "utf8"),
).snapshot.snapshot;

// REAL-SYSTEM SAFETY: nothing here registers Snow at logon (the shell never does), every run uses
// its own user-data directory, and every app, hub and directory is closed even when a test fails:
// the tray icon and the always-on-top mini window must never be left on the user's screen.
const apps: ElectronApplication[] = [];
const hubs: MockHub[] = [];
const dirs: string[] = [];
test.afterEach(async () => {
  for (const app of apps.splice(0)) await app.close().catch(() => undefined);
  for (const hub of hubs.splice(0)) await hub.close().catch(() => undefined);
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

interface WinInfo {
  title: string;
  visible: boolean;
  bounds: { x: number; y: number; width: number; height: number };
}
interface Hook {
  state: () => { stateWord: string; muted: boolean; attention: boolean; online: boolean };
  tooltip: () => string;
  menuLabels: () => { label: string; enabled: boolean }[];
  clickMenu: (label: string) => boolean;
  clickTray: () => void;
  iconSizes: () => number[];
  iconHash: () => string | null;
}
interface Ctx {
  app: ElectronApplication;
  hub: MockHub;
  dash: Page;
  userData: string;
  emit: (type: string, fields?: Record<string, unknown>) => void;
  windows: () => Promise<WinInfo[]>;
  hook: <T>(fn: (h: Hook) => T) => Promise<T>;
  mini: () => Promise<Page>;
}

const newDir = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "snow-hud-e2e-"));
  dirs.push(dir);
  return dir;
};

const envFor = (hub: MockHub, userData: string) => ({
  ...process.env,
  SNOW_HUB_URL: hub.url,
  SNOW_TOKEN: hub.token,
  SNOW_HUD_TEST: "1",
  SNOW_HUD_USER_DATA: userData,
});

async function launch(
  hub: MockHub,
  userData: string,
  flags: string[] = [],
): Promise<{ app: ElectronApplication; ctx: Ctx }> {
  const app = await electron.launch({
    args: [".", ...flags],
    cwd: hudDir,
    env: envFor(hub, userData),
  });
  apps.push(app);
  const dash = await app.firstWindow();
  let n = 0;
  const windows = () =>
    app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows().map((w) => ({
        title: w.getTitle(),
        visible: w.isVisible(),
        bounds: w.getBounds(),
      })),
    );
  const ctx: Ctx = {
    app,
    hub,
    dash,
    userData,
    windows,
    emit: (type, fields = {}) => {
      n += 1;
      hub.send({
        kind: "event",
        event: { type, source: "voice", seq: n, ts_ns: 1_760_000_000_000_000_000 + n, ...fields },
      } as unknown as EventsSchema);
    },
    hook: (fn) =>
      app.evaluate(
        (_electron, src) =>
          // biome-ignore lint/security/noGlobalEval: test-only access to the SNOW_HUD_TEST hook
          eval(`(${src})`)((globalThis as unknown as { __snowChrome: Hook }).__snowChrome),
        fn.toString(),
      ),
    mini: async () => {
      await expect
        .poll(async () => (await windows()).some((w) => w.title === "Snow mini"))
        .toBe(true);
      for (const p of app.windows()) if ((await p.title()) === "Snow mini") return p;
      throw new Error("mini page not found");
    },
  };
  // The shell is up once the dashboard page's socket is.
  await expect.poll(() => ctx.hook((h) => h.state().online), { timeout: 15_000 }).toBe(true);
  return { app, ctx };
}

async function withApp(
  snapshot: Partial<Snapshot>,
  flags: string[],
  run: (ctx: Ctx) => Promise<void>,
  userData = newDir(),
) {
  const hub = await startMockHub({
    script: [],
    snapshot: { ...base, rows: [], subsystems: [], roles: [], ...snapshot },
  });
  hubs.push(hub);
  const { ctx } = await launch(hub, userData, flags);
  await run(ctx);
}

const find = (list: WinInfo[], title: string) => list.find((w) => w.title === title);
const visibleForms = async (c: Ctx) => {
  const l = await c.windows();
  return [find(l, "Snow")?.visible ?? false, find(l, "Snow mini")?.visible ?? false];
};
const commands = (hub: MockHub) =>
  hub.received
    .map((m) => (m as { command?: Record<string, unknown> }).command)
    .filter((c): c is Record<string, unknown> => c !== undefined);

// Pointer events dispatched in the mini page with chosen screen coordinates: real mouse input would
// make the pointer's screen position depend on where the window currently is.
const pointer = (mini: Page, type: string, screenX: number, screenY: number) =>
  mini.evaluate(
    ([t, sx, sy]) => {
      const orb = document.querySelector('[data-testid="mini-orb"]');
      orb?.dispatchEvent(
        new PointerEvent(t as string, {
          bubbles: true,
          pointerId: 1,
          button: 0,
          buttons: t === "pointerup" ? 0 : 1,
          screenX: sx as number,
          screenY: sy as number,
        }),
      );
    },
    [type, screenX, screenY],
  );

const workArea = (c: Ctx) => c.app.evaluate(({ screen }) => screen.getPrimaryDisplay().workArea);

for (const flag of ["--autostart", "--restarted"]) {
  test(`launched with ${flag} only the mini indicator shows`, async () => {
    await withApp({ presence: "sleeping" }, [flag], async (c) => {
      await expect.poll(() => visibleForms(c)).toEqual([false, true]);
      // The hidden dashboard renders nothing, but its page is up: it owns the hub socket.
      await expect(c.dash.getByTestId("state-word")).toHaveCount(0);
      expect(await c.hook((h) => h.state().online)).toBe(true);
      // A tray click opens the dashboard and puts the mini away.
      await c.hook((h) => h.clickTray());
      await expect.poll(() => visibleForms(c)).toEqual([true, false]);
      await expect(c.dash.getByTestId("state-word")).toBeVisible();
    });
  });
}

test("a manual launch shows the dashboard, and the mini only once it is closed", async () => {
  await withApp({ presence: "sleeping" }, [], async (c) => {
    await expect.poll(() => visibleForms(c)).toEqual([true, false]);
    await expect(c.dash.getByTestId("state-word")).toBeVisible();
  });
});

test("a second launch exits and the first instance shows its dashboard", async () => {
  const userData = newDir();
  await withApp(
    { presence: "sleeping" },
    ["--autostart"],
    async (c) => {
      await expect.poll(() => visibleForms(c)).toEqual([false, true]);
      const exe = await c.app.evaluate(() => process.execPath);
      const second = spawn(exe, [".", "--autostart"], {
        cwd: hudDir,
        env: envFor(c.hub, userData),
        stdio: "ignore",
      });
      try {
        const code = await new Promise<number | null>((done, fail) => {
          const timer = setTimeout(
            () => fail(new Error("the second instance did not exit")),
            20_000,
          );
          second.once("exit", (exitCode) => {
            clearTimeout(timer);
            done(exitCode);
          });
        });
        expect(code).toBe(0);
      } finally {
        if (second.exitCode === null) second.kill(); // only the process this test started
      }
      await expect.poll(() => visibleForms(c)).toEqual([true, false]);
    },
    userData,
  );
});

test("a click under 4 px opens the dashboard; 4 px or more drags the window and never opens it", async () => {
  await withApp({ presence: "sleeping" }, ["--autostart"], async (c) => {
    const mini = await c.mini();
    await expect.poll(() => visibleForms(c)).toEqual([false, true]);

    // 3 px of wobble then release is a click.
    await pointer(mini, "pointerdown", 500, 500);
    await pointer(mini, "pointermove", 502, 502);
    await pointer(mini, "pointerup", 502, 502);
    await expect.poll(() => visibleForms(c)).toEqual([true, false]);
    expect(existsSync(join(c.userData, "mini-position.json"))).toBe(false);

    await c.app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()
        .find((w) => w.getTitle() === "Snow")
        ?.close();
    });
    await expect.poll(() => visibleForms(c)).toEqual([false, true]);
    const start = find(await c.windows(), "Snow mini")?.bounds ?? {
      x: 0,
      y: 0,
      width: 0,
      height: 0,
    };

    // A drag: the window follows the pointer by the total movement, the dashboard stays hidden.
    await pointer(mini, "pointerdown", 500, 500);
    await pointer(mini, "pointermove", 480, 510);
    await pointer(mini, "pointermove", 400, 540);
    await expect
      .poll(async () => find(await c.windows(), "Snow mini")?.bounds.x)
      .toBeCloseTo(start.x - 100, -1);
    const moved = find(await c.windows(), "Snow mini")?.bounds ?? start;
    expect(Math.abs(moved.x - (start.x - 100))).toBeLessThanOrEqual(2);
    expect(Math.abs(moved.y - (start.y + 40))).toBeLessThanOrEqual(2);
    expect([moved.width, moved.height]).toEqual([320, 56]);
    await pointer(mini, "pointerup", 400, 540);

    expect(await visibleForms(c)).toEqual([false, true]);
    const saved = JSON.parse(readFileSync(join(c.userData, "mini-position.json"), "utf8"));
    expect(Math.abs(saved.x - moved.x)).toBeLessThanOrEqual(2);
    expect(Math.abs(saved.y - moved.y)).toBeLessThanOrEqual(2);
    expect(typeof saved.displayId).toBe("number");
  });
});

test("dropped past a screen edge the mini snaps back inside the work area", async () => {
  await withApp({ presence: "sleeping" }, ["--autostart"], async (c) => {
    const mini = await c.mini();
    const work = await workArea(c);
    await pointer(mini, "pointerdown", 500, 500);
    await pointer(mini, "pointermove", 4500, 3500);
    await pointer(mini, "pointerup", 4500, 3500);
    await expect
      .poll(async () => {
        const b = find(await c.windows(), "Snow mini")?.bounds;
        return b
          ? b.x + b.width <= work.x + work.width && b.y + b.height <= work.y + work.height
          : false;
      })
      .toBe(true);
    const b = find(await c.windows(), "Snow mini")?.bounds ?? { x: 0, y: 0, width: 0, height: 0 };
    // Pulled all the way to the bottom-right corner of the work area (2 px for display rounding).
    expect(Math.abs(b.x + b.width - (work.x + work.width))).toBeLessThanOrEqual(2);
    expect(Math.abs(b.y + b.height - (work.y + work.height))).toBeLessThanOrEqual(2);
  });
});

test("the row mirrors on the left half of the display and the position is remembered across launches", async () => {
  const userData = newDir();
  await withApp(
    { presence: "sleeping" },
    ["--autostart"],
    async (c) => {
      const mini = await c.mini();
      const row = mini.getByTestId("mini-row");
      await expect(row).toHaveAttribute("data-side", "right");
      const work = await workArea(c);

      await pointer(mini, "pointerdown", 2000, 500);
      await pointer(mini, "pointermove", 2000 - work.width * 0.8, 500);
      await expect(row).toHaveAttribute("data-side", "left");
      // [orb][caption]: the orb is the first thing in the row.
      expect(await row.evaluate((el) => el.firstElementChild?.getAttribute("data-testid"))).toBe(
        "mini-orb",
      );
      await pointer(mini, "pointerup", 2000 - work.width * 0.8, 500);
      await expect(row).toHaveAttribute("data-side", "left");
    },
    userData,
  );
  const first = JSON.parse(readFileSync(join(userData, "mini-position.json"), "utf8"));
  expect(first.x).toBeLessThan(200);
  await apps.pop()?.close();

  // A fresh launch puts the mini back where it was left.
  await withApp(
    { presence: "sleeping" },
    ["--autostart"],
    async (c) => {
      const mini = await c.mini();
      await expect(mini.getByTestId("mini-row")).toHaveAttribute("data-side", "left");
      await expect
        .poll(async () =>
          Math.abs((find(await c.windows(), "Snow mini")?.bounds.x ?? 9999) - first.x),
        )
        .toBeLessThanOrEqual(2);
    },
    userData,
  );
});

test("a saved position on a display that is gone resets to the top-right corner", async () => {
  const userData = newDir();
  writeFileSync(
    join(userData, "mini-position.json"),
    JSON.stringify({ x: 5000, y: 300, displayId: 987654321 }),
  );
  await withApp(
    { presence: "sleeping" },
    ["--autostart"],
    async (c) => {
      await c.mini();
      const work = await workArea(c);
      await expect.poll(async () => find(await c.windows(), "Snow mini")?.visible).toBe(true);
      const b = find(await c.windows(), "Snow mini")?.bounds ?? { x: 0, y: 0, width: 0, height: 0 };
      expect(Math.abs(b.x + b.width - (work.x + work.width - 16))).toBeLessThanOrEqual(2);
      expect(Math.abs(b.y - (work.y + 16))).toBeLessThanOrEqual(2);
    },
    userData,
  );
});

test("tooltip, menu, orb icon and the confirmed mute label follow the core", async () => {
  await withApp({ presence: "listening" }, [], async (c) => {
    await expect.poll(() => c.hook((h) => h.tooltip())).toBe("Snow: Listening");
    expect(await c.hook((h) => h.menuLabels())).toEqual([
      { label: "Open Snow", enabled: true },
      { label: "Mute microphone", enabled: true },
      { label: "Quit Snow", enabled: true },
    ]);
    // The orb is the icon: a 16 px and a 32 px rendering.
    await expect.poll(() => c.hook((h) => h.iconSizes())).toEqual([16, 32]);
    const listening = await c.hook((h) => h.iconHash());

    // A Down subsystem adds the suffix until it is healthy.
    const sub = (status: string) =>
      c.emit("health.subsystem", {
        name: "speech_to_text",
        label: "Speech to text",
        owner: "voice",
        status,
        detail: null,
      });
    sub("down");
    await expect.poll(() => c.hook((h) => h.tooltip())).toBe("Snow: Listening (attention)");
    sub("running");
    await expect.poll(() => c.hook((h) => h.tooltip())).toBe("Snow: Listening");

    // The state hue is in the icon.
    c.emit("presence.state", { state: "thinking", mode: "awake" });
    await expect.poll(() => c.hook((h) => h.tooltip())).toBe("Snow: Thinking");
    await expect.poll(() => c.hook((h) => h.iconHash())).not.toBe(listening);

    // Mute from the tray sends the command by "tray" and changes nothing until the core confirms.
    c.emit("presence.state", { state: "listening", mode: "awake" });
    await expect.poll(() => c.hook((h) => h.tooltip())).toBe("Snow: Listening");
    // The icon eases back from the thinking hue; a slow runner is still mid-fade here.
    await expect.poll(() => c.hook((h) => h.iconHash())).toBe(listening);
    const unmuted = listening;
    expect(await c.hook((h) => h.clickMenu("Mute microphone"))).toBe(true);
    await expect
      .poll(() => commands(c.hub).filter((m) => m.type === "cmd.mute.set"))
      .toEqual([{ type: "cmd.mute.set", muted: true, by: "tray" }]);
    await c.dash.waitForTimeout(400);
    expect((await c.hook((h) => h.menuLabels()))[1].label).toBe("Mute microphone");
    expect(await c.hook((h) => h.iconHash())).toBe(unmuted);

    c.emit("mute.changed", { muted: true, by: "tray" });
    c.emit("presence.state", { state: "muted", mode: "awake" });
    await expect
      .poll(async () => (await c.hook((h) => h.menuLabels()))[1].label)
      .toBe("Unmute microphone");
    // The muted icon carries the slash, so it is not the plain one.
    await expect.poll(() => c.hook((h) => h.iconHash())).not.toBe(unmuted);
    expect(await c.hook((h) => h.clickMenu("Unmute microphone"))).toBe(true);
    await expect
      .poll(() =>
        commands(c.hub)
          .filter((m) => m.type === "cmd.mute.set")
          .at(-1),
      )
      .toEqual({ type: "cmd.mute.set", muted: false, by: "tray" });
  });
});

test("with the core unreachable mute is disabled and sends nothing", async () => {
  await withApp({ presence: "listening" }, [], async (c) => {
    await expect.poll(() => c.hook((h) => h.tooltip())).toBe("Snow: Listening");
    await c.hub.close();
    await expect.poll(() => c.hook((h) => h.state().online), { timeout: 15_000 }).toBe(false);
    await expect.poll(() => c.hook((h) => h.tooltip())).toBe("Snow: Reconnecting");
    const labels = await c.hook((h) => h.menuLabels());
    expect(labels.find((l) => l.label === "Mute microphone")?.enabled).toBe(false);
    expect(labels.find((l) => l.label === "Quit Snow")?.enabled).toBe(true);
    expect(await c.hook((h) => h.clickMenu("Mute microphone"))).toBe(false);
    expect(commands(c.hub).filter((m) => m.type === "cmd.mute.set")).toEqual([]);
  });
});

// Resolves when the app's process has gone; set up before the quit is asked for.
const exitOf = (app: ElectronApplication): Promise<number> => {
  const proc = app.process();
  const started = Date.now();
  return new Promise((done) => {
    if (proc.exitCode !== null) return done(0);
    proc.once("exit", () => done(Date.now() - started));
  });
};

test("Quit Snow sends cmd.app.quit to the core and then the app exits", async () => {
  await withApp({ presence: "listening" }, [], async (c) => {
    const exited = exitOf(c.app);
    expect(await c.hook((h) => h.clickMenu("Quit Snow"))).toBe(true);
    await expect
      .poll(() => commands(c.hub).filter((m) => m.type === "cmd.app.quit"))
      .toEqual([{ type: "cmd.app.quit" }]);
    // The mock core does not exit, so the shell stops waiting after its grace period.
    await Promise.race([
      exited,
      new Promise((_, fail) => setTimeout(() => fail(new Error("app did not quit")), 15_000)),
    ]);
  });
});

test("Quit Snow quits locally and at once when the core is unreachable", async () => {
  await withApp({ presence: "listening" }, [], async (c) => {
    await c.hub.close();
    await expect.poll(() => c.hook((h) => h.state().online), { timeout: 15_000 }).toBe(false);
    const exited = exitOf(c.app);
    await c.hook((h) => h.clickMenu("Quit Snow"));
    const ms = await Promise.race([
      exited,
      new Promise<number>((_, fail) =>
        setTimeout(() => fail(new Error("app did not quit")), 10_000),
      ),
    ]);
    expect(ms).toBeLessThan(2500);
    expect(commands(c.hub).filter((m) => m.type === "cmd.app.quit")).toEqual([]);
  });
});

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { _electron as electron, expect, type Page, test } from "@playwright/test";
import type { EventsSchema, Snapshot } from "../src/generated/contracts";
import type { SnowTestHook } from "../src/renderer/src/orb/renderer";
import { type MockHub, startMockHub } from "./mockHub";

const hudDir = resolve(__dirname, "..");
const base: Snapshot = JSON.parse(
  readFileSync(resolve(hudDir, "../contracts/samples/events.json"), "utf8"),
).snapshot.snapshot;

interface Ctx {
  win: Page;
  hub: MockHub;
  emit: (type: string, fields?: Record<string, unknown>) => void;
}

// An empty mock hub plus the real Electron HUD (with the orb test hook on), both closed afterwards.
async function withHud(snapshot: Partial<Snapshot>, run: (ctx: Ctx) => Promise<void>) {
  const hub = await startMockHub({ script: [], snapshot: { ...base, rows: [], ...snapshot } });
  const app = await electron.launch({
    args: ["."],
    cwd: hudDir,
    env: {
      ...process.env,
      SNOW_HUB_URL: hub.url,
      SNOW_TOKEN: hub.token,
      SNOW_HUD_TEST: "1", // exposes window.__snowTest so the orb's state can be read
    },
  });
  try {
    const win = await app.firstWindow();
    await expect(win.getByTestId("state-word")).not.toHaveText("Reconnecting");
    await expect(win.getByTestId("mute-button")).toBeEnabled();
    let n = 0;
    const emit: Ctx["emit"] = (type, fields = {}) => {
      n += 1;
      hub.send({
        kind: "event",
        event: { type, source: "voice", seq: n, ts_ns: 1_760_000_000_000_000_000 + n, ...fields },
      } as unknown as EventsSchema);
    };
    await run({ win, hub, emit });
  } finally {
    await app.close();
    await hub.close();
  }
}

const orbState = (win: Page) =>
  win.evaluate(
    () => (window as Window & { __snowTest?: SnowTestHook }).__snowTest?.orbStats()?.state,
  );

const muteCommands = (hub: MockHub) =>
  hub.received.filter(
    (m) => (m as { command?: { type?: string } }).command?.type === "cmd.mute.set",
  );

test("the Mute button flips only when the hub confirms: pressed state, then banner, muted orb and Unmute", async () => {
  await withHud({ muted: false, presence: "listening" }, async ({ win, hub, emit }) => {
    const button = win.getByTestId("mute-button");
    await expect(button).toHaveText("Mute microphone");
    await expect(win.getByTestId("mute-banner")).toHaveCount(0);

    await button.evaluate((el) => {
      const seen: Array<string | null> = [];
      new MutationObserver(() => seen.push(el.getAttribute("data-pressed"))).observe(el, {
        attributes: true,
        attributeFilter: ["data-pressed"],
      });
      (window as Window & { __pressed?: Array<string | null> }).__pressed = seen;
    });
    await button.click();

    await expect.poll(() => muteCommands(hub).length).toBe(1);
    expect(muteCommands(hub)[0]).toEqual({
      kind: "command",
      command: { type: "cmd.mute.set", muted: true, by: "hud" },
    });
    // The 120 ms pressed state came and went, and nothing else changed: the hub has not answered.
    await expect
      .poll(() => win.evaluate(() => (window as Window & { __pressed?: unknown }).__pressed))
      .toEqual(["true", "false"]);
    await expect(button).toHaveText("Mute microphone");
    await expect(win.getByTestId("mute-banner")).toHaveCount(0);
    await expect(win.getByTestId("state-word")).toHaveText("Listening");
    expect(await orbState(win)).toBe("listening");

    // The hub confirms (as the voice worker would): now the UI changes, in all three places.
    emit("mute.changed", { muted: true, by: "hud" });
    emit("presence.state", { state: "muted", mode: "awake" });
    await expect(button).toHaveText("Unmute microphone");
    const banner = win.getByTestId("mute-banner");
    await expect(banner).toContainText("Microphone is muted. Snow cannot hear you.");
    await expect(win.getByTestId("banner-unmute-button")).toHaveText("Unmute microphone");
    await expect(win.getByTestId("state-word")).toHaveText("Muted");
    await expect.poll(() => orbState(win)).toBe("muted");
    // Alert hue on the label and border while muted.
    await expect
      .poll(() =>
        button.evaluate((el) => {
          const s = getComputedStyle(el);
          return [s.color, s.borderTopColor];
        }),
      ) // polled: the colors settle over the 120 ms transition
      .toEqual(["rgb(248, 113, 113)", "rgb(248, 113, 113)"]);
    await expect(win.getByTestId("empty-state")).toContainText("Microphone is muted");
    await expect(win.getByTestId("empty-state")).toContainText(
      "Snow cannot hear you. Click Unmute microphone to turn it back on.",
    );
  });
});

test("Unmute from the banner or the orb sends the command and waits for mute.changed", async () => {
  await withHud({ muted: true, presence: "muted" }, async ({ win, hub, emit }) => {
    const banner = win.getByTestId("mute-banner");
    await expect(banner).toBeVisible();
    await expect(win.getByTestId("mute-button")).toHaveText("Unmute microphone");

    await win.getByTestId("banner-unmute-button").click();
    await expect.poll(() => muteCommands(hub).length).toBe(1);
    expect((muteCommands(hub)[0] as { command: unknown }).command).toEqual({
      type: "cmd.mute.set",
      muted: false,
      by: "hud",
    });
    await win.waitForTimeout(300);
    await expect(banner).toBeVisible(); // not optimistic
    await expect(win.getByTestId("state-word")).toHaveText("Muted");

    // The dashboard orb is the same control (D-10: unmute by click only).
    await win.getByRole("button", { name: /^Snow,/ }).click();
    await expect.poll(() => muteCommands(hub).length).toBe(2);
    expect((muteCommands(hub)[1] as { command: { muted: boolean } }).command.muted).toBe(false);

    emit("mute.changed", { muted: false, by: "hud" });
    emit("presence.state", { state: "sleeping", mode: "awake" });
    await expect(banner).toHaveCount(0);
    await expect(win.getByTestId("mute-button")).toHaveText("Mute microphone");
    await expect(win.getByTestId("state-word")).toHaveText("Standing by");
  });
});

test("a mute by voice shows the banner with no click, and the status region says so", async () => {
  await withHud({ muted: false, presence: "listening" }, async ({ win, emit }) => {
    const status = win.getByRole("status");
    emit("mute.changed", { muted: true, by: "voice" });
    emit("presence.state", { state: "muted", mode: "awake" });
    await expect(win.getByTestId("mute-banner")).toBeVisible();
    await expect(status).toHaveText("Microphone muted");

    emit("mute.changed", { muted: false, by: "hud" });
    await expect(status).toHaveText("Microphone unmuted");

    emit("health.subsystem", {
      name: "speech_to_text",
      label: "Speech to text",
      owner: "voice",
      status: "down",
      detail: null,
    });
    await expect(status).toHaveText("Speech to text down");
  });
});

test("offline, the Mute button is disabled, the connection banner explains it and no mute claim is made", async () => {
  await withHud({ muted: true, presence: "muted" }, async ({ win, hub }) => {
    await expect(win.getByTestId("mute-banner")).toBeVisible();
    await hub.close();
    const banner = win.getByTestId("connection-banner");
    await expect(banner).toBeVisible({ timeout: 15_000 });
    await expect(banner).toContainText(
      "Reconnecting automatically. Mute is unavailable until the connection returns.",
    );
    await expect(win.getByTestId("mute-button")).toBeDisabled();
    await expect(win.getByTestId("mute-banner")).toHaveCount(0);
    await expect(win.getByRole("status")).toHaveText("Connection to Snow's core lost");
    await expect(win.getByTestId("state-word")).toHaveText("Reconnecting");
    expect(await orbState(win)).toBe("offline");
  });
});

test("soft sleep shows the Asleep chip under the state word and never the mute banner", async () => {
  await withHud({ muted: false, presence: "sleeping", mode: "soft_sleep" }, async ({ win }) => {
    await expect(win.getByTestId("state-word")).toHaveText("Standing by");
    await expect(win.getByTestId("mode-chip")).toHaveText("Asleep");
    await expect(win.getByTestId("mute-banner")).toHaveCount(0);
    await expect(win.getByTestId("empty-state")).toContainText("Snow is asleep");
  });
});

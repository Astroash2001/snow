import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { _electron as electron, expect, type Page, test } from "@playwright/test";
import type { EventsSchema, Snapshot } from "../src/generated/contracts";
import type { SnowTestHook } from "../src/renderer/src/orb/renderer";
import { startMockHub } from "./mockHub";

const hudDir = resolve(__dirname, "..");
const samples = resolve(hudDir, "../contracts/samples");
const base: Snapshot = JSON.parse(readFileSync(resolve(samples, "events.json"), "utf8")).snapshot
  .snapshot;

// The fixed 12-turn conversation. Its last two events (conversation.ended and the drop to sleeping)
// start the 2 s hold and fade, which would race the screenshot, so the replay stops before them: the
// dashboard is left exactly as it looks mid-conversation, all twelve turns on screen.
const conversation: EventsSchema[] = readFileSync(resolve(samples, "conversation-12.jsonl"), "utf8")
  .split("\n")
  .filter((l) => l.trim() !== "")
  .map((l) => JSON.parse(l))
  .slice(0, -2);

const TS = 1_760_000_000_000_000_000;
const ORB_SEED = 7;

const subsystem = (name: string, label: string) => ({
  type: "health.subsystem" as const,
  name,
  label,
  owner: "voice" as const,
  source: "voice" as const,
  status: "running" as const,
  ts_ns: TS,
});
const provider = (id: string, label: string, status: "ready" | "active" | "not_configured") => ({
  type: "health.provider" as const,
  provider: id,
  label,
  status,
  source: "brain" as const,
  ts_ns: TS,
});
const entry = (
  id: string,
  label: string,
  model: string,
  status: "active" | "ready" | "not_configured",
) => ({
  provider: id,
  provider_label: label,
  model,
  status,
});
const chain = [
  entry("experiential", "Experiential Labs", "gpt-5.6-luna", "ready"),
  entry("google", "Google AI Studio", "gemini-flash", "active"),
  entry("nim", "NVIDIA NIM", "deepseek-v4-pro", "not_configured"),
  entry("openrouter", "OpenRouter", "nemotron-3-super:free", "not_configured"),
];

// What the dashboard knows before the conversation starts: a healthy core, a brain already on its
// second model, the everyday voice, and Groq speech-to-text (the fixture itself flips that to local).
const snapshot: Snapshot = {
  ...base,
  rows: [],
  presence: "listening",
  subsystems: [
    subsystem("wake_word", "Wake word"),
    subsystem("speech_to_text", "Speech to text"),
    subsystem("speech_output", "Speech output"),
    subsystem("brain", "Brain"),
    subsystem("event_log", "Event log"),
  ],
  providers: [
    provider("experiential", "Experiential Labs", "ready"),
    provider("groq", "Groq", "ready"),
    provider("google", "Google AI Studio", "active"),
    provider("nim", "NVIDIA NIM", "not_configured"),
    provider("openrouter", "OpenRouter", "not_configured"),
  ],
  roles: [
    {
      type: "health.role",
      role: "brain",
      status: "fallback",
      entries: chain,
      active_index: 1,
      active_provider: "google",
      active_model: "gemini-flash",
      source: "brain",
      ts_ns: TS,
    },
    {
      type: "health.role",
      role: "fast",
      status: "active",
      entries: [entry("groq", "Groq", "openai/gpt-oss-120b", "active")],
      active_index: 0,
      active_provider: "groq",
      active_model: "openai/gpt-oss-120b",
      source: "brain",
      ts_ns: TS,
    },
    {
      type: "health.role",
      role: "vision",
      status: "not_used_yet",
      entries: [entry("experiential", "Experiential Labs", "gpt-5.6-luna", "ready")],
      active_index: null,
      source: "brain",
      ts_ns: TS,
    },
  ],
  voice: {
    type: "voice.status",
    engine: "pocket_tts",
    voice_name: "Snow",
    voice_role: "everyday",
    cartesia_available: true,
    cartesia_reason: "ok",
    credits_remaining: 9000,
    source: "voice",
    ts_ns: TS,
  },
  stt: {
    type: "stt.status",
    stt_source: "groq",
    status_reason: "primary",
    retry_after_ns: null,
    source: "voice",
    ts_ns: TS,
  },
};

type TestWindow = Window & { __snowTest?: SnowTestHook };
const frames = (win: Page) =>
  win.evaluate(() => (window as TestWindow).__snowTest?.orbStats()?.frames ?? 0);

test("the dashboard replaying the 12-turn fixture matches the committed baseline", async () => {
  test.setTimeout(90_000);
  const hub = await startMockHub({ script: conversation, snapshot, intervalMs: 10 });
  const app = await electron.launch({
    // Fixed scale factor: the baseline must not depend on the display's Windows scaling. The other
    // flags keep an occluded window painting (see perf.spec.ts); test runs only.
    args: [
      ".",
      "--force-device-scale-factor=1",
      "--disable-backgrounding-occluded-windows",
      "--disable-renderer-backgrounding",
      "--disable-features=CalculateNativeWinOcclusion",
    ],
    cwd: hudDir,
    env: {
      ...process.env,
      SNOW_HUB_URL: hub.url,
      SNOW_TOKEN: hub.token,
      SNOW_HUD_TEST: "1", // exposes window.__snowTest.freezeOrb
    },
  });
  try {
    const win = await app.firstWindow();
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0].setContentSize(960, 640);
    });
    await expect(win.getByTestId("mute-button")).toBeEnabled();

    // All twelve turns, then a beat for the last few events (speaking, listening) to land.
    await expect(win.getByTestId("row-user")).toHaveCount(12, { timeout: 20_000 });
    await expect(win.getByTestId("row-snow").last()).toContainText("Anytime. Talk later.");
    await win.waitForTimeout(500);
    await expect(win.getByTestId("state-word")).toHaveText("Listening");
    await expect(win.getByTestId("row-system")).toHaveCount(1);
    const interrupted = win.getByTestId("row-snow").filter({ hasText: "The last commit says fix" });
    await expect(interrupted).toHaveAttribute("data-interrupted", "true");

    // Everything that paints on its own clock is settled before the picture is taken: fonts, the
    // 16 px Snow avatars, and the big orb (frozen on a fixed seed, redrawn once).
    await win.evaluate(() => document.fonts.ready.then(() => undefined));
    await expect
      .poll(() =>
        win.getByTestId("snow-avatar").evaluateAll((cs) =>
          cs.every((c) => {
            const canvas = c as HTMLCanvasElement;
            const data =
              canvas.getContext("2d")?.getImageData(0, 0, canvas.width, canvas.height).data ?? [];
            return data.some((v, i) => i % 4 === 3 && v > 0);
          }),
        ),
      )
      .toBe(true);
    await expect
      .poll(() => win.evaluate(() => (window as TestWindow).__snowTest?.orbStats()?.atlases ?? 0))
      .toBeGreaterThan(0);
    const before = await frames(win);
    await win.evaluate((seed) => (window as TestWindow).__snowTest?.freezeOrb(seed), ORB_SEED);
    await expect.poll(() => frames(win)).toBeGreaterThan(before);
    // The list follows the newest turn; scroll back so the picture holds the interrupted reply, the
    // provider-switch system row and the Jump to latest pill, not just the last four messages.
    await interrupted.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await expect(win.getByTestId("jump-to-latest")).toBeVisible();
    await win.mouse.move(0, 0); // no hover state over any row
    await win.waitForTimeout(300);

    await expect(win).toHaveScreenshot("dashboard-12-turns.png", {
      maxDiffPixelRatio: 0.01,
      animations: "disabled",
      caret: "hide",
    });
  } finally {
    await app.close();
    await hub.close();
  }
});

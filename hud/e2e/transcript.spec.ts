import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { _electron as electron, expect, type Page, test } from "@playwright/test";
import type { EventsSchema, Snapshot } from "../src/generated/contracts";
import { type MockHub, startMockHub } from "./mockHub";

const hudDir = resolve(__dirname, "..");
const base: Snapshot = JSON.parse(
  readFileSync(resolve(hudDir, "../contracts/samples/events.json"), "utf8"),
).snapshot.snapshot;

interface Ctx {
  win: Page;
  hub: MockHub;
  /** Push one event to the HUD; ts_ns and seq are filled in. */
  emit: (type: string, fields?: Record<string, unknown>) => void;
}

// Starts an empty mock hub and the real Electron HUD against it; the snapshot is the sample one with
// no rows unless a test overrides it. Always closes both, even when the test fails.
async function withHud(snapshot: Partial<Snapshot>, run: (ctx: Ctx) => Promise<void>) {
  const hub = await startMockHub({ script: [], snapshot: { ...base, rows: [], ...snapshot } });
  const app = await electron.launch({
    args: ["."],
    cwd: hudDir,
    env: { ...process.env, SNOW_HUB_URL: hub.url, SNOW_TOKEN: hub.token },
  });
  try {
    const win = await app.firstWindow();
    // The mute button is enabled only once the first snapshot has arrived.
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

const turn = { turn_id: "t1" };

test("the partial transcript is replaced wholesale, then becomes a final row", async () => {
  await withHud({}, async ({ win, emit }) => {
    const partial = win.getByTestId("row-partial");
    emit("transcript.partial", { ...turn, text: "hel" });
    await expect(partial).toContainText("hel");
    emit("transcript.partial", { ...turn, text: "hello sn" });
    await expect(partial).toContainText("hello sn");
    await expect(partial).not.toContainText("hel hello");
    // Live words read in text-2 (#A8B1C5) with an accent underline.
    const color = await partial.locator("p").evaluate((el) => getComputedStyle(el).color);
    expect(color).toBe("rgb(168, 177, 197)");

    emit("transcript.final", { ...turn, text: "hello snow" });
    await expect(partial).toHaveCount(0);
    const row = win.getByTestId("row-user");
    await expect(row).toHaveText(/hello snow/);
    const final = await row.locator("p").evaluate((el) => getComputedStyle(el).color);
    expect(final).toBe("rgb(230, 234, 242)");
  });
});

test("a turn that ends without speech removes the partial row and adds no row", async () => {
  await withHud({}, async ({ win, emit }) => {
    emit("transcript.partial", { ...turn, text: "um" });
    await expect(win.getByTestId("row-partial")).toBeVisible();
    emit("presence.state", { state: "sleeping", mode: "awake" });
    await expect(win.getByTestId("row-partial")).toHaveCount(0);
    await expect(win.getByTestId("row-user")).toHaveCount(0);
    await expect(win.getByTestId("empty-state")).toBeVisible();
  });
});

test("Snow's row appears with the first delta, grows, and a silent fallback adds none", async () => {
  await withHud({}, async ({ win, emit }) => {
    emit("transcript.final", { ...turn, text: "good morning snow" });
    emit("presence.state", { state: "thinking", mode: "awake" });
    await expect(win.getByTestId("state-word")).toHaveText("Thinking");
    await expect(win.getByTestId("row-snow")).toHaveCount(0); // no placeholder bubble while thinking

    emit("reply.delta", { ...turn, text: "Good " });
    const snow = win.getByTestId("row-snow");
    await expect(snow).toContainText("Good");
    await expect(snow).toHaveAttribute("aria-busy", "true");
    await expect(snow.getByTestId("snow-avatar")).toBeVisible();
    // The 16 px orb avatar was painted (some non-transparent pixel), not left blank.
    await expect
      .poll(() =>
        snow.getByTestId("snow-avatar").evaluate((c: HTMLCanvasElement) => {
          const data = c.getContext("2d")?.getImageData(0, 0, c.width, c.height).data ?? [];
          return data.some((v, i) => i % 4 === 3 && v > 0);
        }),
      )
      .toBe(true);
    emit("reply.delta", { ...turn, text: "morning" });
    await expect(snow.locator("p")).toHaveText("Good morning");
    emit("reply.final", { ...turn, text: "Good morning.", emotion: "warm", reply_source: "llm" });
    await expect(snow.locator("p")).toHaveText("Good morning.");
    await expect(snow).not.toHaveAttribute("aria-busy", /.*/);

    // The next turn gets the silent fallback: an empty final, so no row.
    emit("reply.final", {
      turn_id: "t2",
      text: "",
      emotion: "neutral",
      reply_source: "fallback",
    });
    await win.waitForTimeout(300);
    await expect(win.getByTestId("row-snow")).toHaveCount(1);
  });
});

test("an interrupted reply keeps the text heard, dims it and shows the chip", async () => {
  await withHud({}, async ({ win, emit }) => {
    emit("reply.final", { ...turn, text: "The last commit says fix", reply_source: "llm" });
    const snow = win.getByTestId("row-snow");
    await expect(snow.locator("p")).toHaveText("The last commit says fix");
    const live = await snow.locator("p").evaluate((el) => getComputedStyle(el).color);
    expect(live).toBe("rgb(230, 234, 242)");

    emit("reply.interrupted", { ...turn, spoken_text: "The last commit" });
    await expect(snow.locator("p")).toHaveText("The last commit");
    await expect(snow).toContainText("Interrupted");
    const dim = await snow.locator("p").evaluate((el) => getComputedStyle(el).color);
    expect(dim).toBe("rgb(168, 177, 197)");
  });
});

test("provider switches, privacy holds and exhausted chains are system rows, never a modal", async () => {
  await withHud({}, async ({ win, emit }) => {
    emit("llm.switch", {
      role: "brain",
      from_provider: "experiential",
      from_model: "gpt-5.6-luna",
      to_provider: "groq",
      to_model: "gpt-oss-120b",
      switch_reason: "rate_limit",
    });
    emit("llm.blocked_privacy", { role: "fast", data_class: "private" });
    emit("llm.exhausted", { role: "brain" });
    const rows = win.getByTestId("row-system");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toHaveText("Switched brain model to groq (rate limit).");
    await expect(rows.nth(1)).toHaveText(
      "Request held back: only providers not cleared for private data were available. Add a trusted provider key to continue.",
    );
    await expect(rows.nth(2)).toHaveText(
      "No language model is reachable, so Snow cannot reply. Open Language models below to see which providers failed.",
    );
    await expect(win.getByRole("dialog")).toHaveCount(0);
  });
});

test("system rows from a snapshot render the same sentence as live ones", async () => {
  const rows: Snapshot["rows"] = [
    {
      kind: "system",
      row_id: "9",
      text: "role=fast from=groq/a to=nim/b reason=bad_key",
      system_event: "llm.switch",
      ts_ns: 1_760_000_000_000_000_000,
      turn_id: null,
      interrupted: false,
    },
  ];
  await withHud({ rows }, async ({ win }) => {
    await expect(win.getByTestId("row-system")).toHaveText(
      "Switched fast model to nim (service error).",
    );
  });
});

test("long conversations scroll; scrolling up pauses follow and Jump to latest resumes it", async () => {
  await withHud({}, async ({ win, emit }) => {
    const log = win.getByTestId("transcript-log");
    const scroller = log.locator("..");
    const jump = win.getByTestId("jump-to-latest");
    const gap = () => scroller.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight);
    const say = (i: number) =>
      emit("transcript.final", { turn_id: `t${i}`, text: `line ${i} `.repeat(30) });

    for (let i = 0; i < 30; i++) say(i);
    await expect(win.getByTestId("row-user")).toHaveCount(30);
    await expect.poll(gap).toBeLessThanOrEqual(24); // followed to the bottom
    await expect(jump).toHaveCount(0);

    await scroller.evaluate((el) => {
      el.scrollTop = 0;
    });
    await expect(jump).toBeVisible();
    await expect(jump).toHaveText("Jump to latest");
    say(100);
    await expect(win.getByTestId("row-user")).toHaveCount(31);
    expect(await scroller.evaluate((el) => el.scrollTop)).toBe(0); // follow stayed paused

    await jump.click();
    await expect.poll(gap).toBeLessThanOrEqual(24);
    await expect(jump).toHaveCount(0);
    say(101);
    await expect(win.getByTestId("row-user")).toHaveCount(32);
    await expect.poll(gap).toBeLessThanOrEqual(24); // follow resumed
  });
});

test("after the conversation ends the rows stay 2 s, fade over 300 ms, then the empty state shows", async () => {
  await withHud({}, async ({ win, emit }) => {
    emit("transcript.final", { ...turn, text: "thanks snow that is all" });
    await expect(win.getByTestId("row-user")).toBeVisible();
    const endedAt = Date.now();
    emit("conversation.ended", { end_reason: "phrase" });
    emit("presence.state", { state: "sleeping", mode: "awake" });

    await win.waitForTimeout(800);
    await expect(win.getByTestId("row-user")).toBeVisible(); // still readable inside the 2 s hold
    await expect(win.getByTestId("empty-state")).toHaveCount(0);

    const scroller = win.getByTestId("transcript-log").locator("..");
    await expect(scroller).toHaveAttribute("data-fading", "true", { timeout: 5_000 });
    expect(Date.now() - endedAt).toBeGreaterThanOrEqual(1_800);
    await expect(win.getByTestId("empty-state")).toBeVisible({ timeout: 5_000 });
    await expect(win.getByTestId("empty-state")).toContainText('Say "Hey Snow" to start');
    await expect(win.getByTestId("empty-state")).toContainText(
      "Snow listens for the wake phrase on this PC. Nothing is sent anywhere until you wake it.",
    );
    await expect(win.getByTestId("row-user")).toHaveCount(0);
  });
});

test("a new conversation inside the 2 s window clears the old rows at once", async () => {
  await withHud({}, async ({ win, emit }) => {
    emit("transcript.final", { ...turn, text: "old words" });
    await expect(win.getByTestId("row-user")).toBeVisible();
    emit("conversation.ended", { end_reason: "silence" });
    await win.waitForTimeout(300);
    emit("conversation.started", { trigger: "wake" });
    await expect(win.getByTestId("row-user")).toHaveCount(0);
    emit("transcript.final", { turn_id: "t2", text: "new words" });
    await win.waitForTimeout(2_600); // past the old timers: the new conversation must survive them
    await expect(win.getByTestId("row-user")).toHaveText(/new words/);
  });
});

test("text is shown as literal characters, never as markup, and long tokens wrap", async () => {
  await withHud({}, async ({ win, emit }) => {
    emit("transcript.final", { ...turn, text: "<b>x</b><img src=x onerror=alert(1)>" });
    emit("reply.final", { ...turn, text: "<i>hi</i>", reply_source: "llm" });
    const user = win.getByTestId("row-user");
    await expect(user.locator("p")).toHaveText("<b>x</b><img src=x onerror=alert(1)>");
    await expect(win.getByTestId("row-snow").locator("p")).toHaveText("<i>hi</i>");
    expect(await win.locator("main b, main i, main img").count()).toBe(0);

    const wrap = await user.locator("p").evaluate((el) => getComputedStyle(el).overflowWrap);
    expect(wrap).toBe("anywhere");
    emit("transcript.final", { turn_id: "t2", text: "A".repeat(400) });
    const long = win.getByTestId("row-user").nth(1);
    await expect(long).toBeVisible();
    const fits = await long
      .locator("p")
      .evaluate(
        (el) => el.scrollWidth <= el.clientWidth + 1 && el.getBoundingClientRect().width > 0,
      );
    expect(fits).toBe(true);
  });
});

test("with no conversation the transcript card shows the empty state for the current presence", async () => {
  await withHud({ presence: "sleeping", mode: "awake" }, async ({ win, emit }) => {
    const empty = win.getByTestId("empty-state");
    await expect(empty).toContainText('Say "Hey Snow" to start');
    await expect(win.getByTestId("mode-chip")).toHaveCount(0);

    emit("presence.state", { state: "sleeping", mode: "soft_sleep" });
    await expect(empty).toContainText("Snow is asleep");
    await expect(empty).toContainText('Say "Hey Snow" to wake it.');
    await expect(win.getByTestId("mode-chip")).toHaveText("Asleep");

    emit("presence.state", { state: "sleeping", mode: "awake" });
    await expect(empty).toContainText('Say "Hey Snow" to start');
  });
});

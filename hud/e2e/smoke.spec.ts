import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import type { EventsSchema } from "../src/generated/contracts";
import { startMockHub } from "./mockHub";

const hudDir = resolve(__dirname, "..");
const conversation: EventsSchema[] = readFileSync(
  resolve(hudDir, "../contracts/samples/conversation-12.jsonl"),
  "utf8",
)
  .split("\n")
  .filter((l) => l.trim() !== "")
  .map((l) => JSON.parse(l));

test("dashboard shows the snapshot, then live rows without a reload", async () => {
  const hub = await startMockHub({ script: [] });
  const app = await electron.launch({
    args: ["."],
    cwd: hudDir,
    env: { ...process.env, SNOW_HUB_URL: hub.url, SNOW_TOKEN: hub.token },
  });
  try {
    const win = await app.firstWindow();
    const word = win.getByTestId("state-word");

    // Snapshot: state word plus the one row it carries.
    await expect(word).toHaveText("Listening");
    await expect(win.getByTestId("row-user")).toHaveText(/what is the time/);

    // Live: turn-1 of the golden conversation (transcript.final, thinking, reply.final).
    for (const msg of conversation.slice(0, 8)) hub.send(msg);
    await expect(
      win.getByTestId("row-user").filter({ hasText: "good morning snow" }),
    ).toBeVisible();
    await expect(
      win.getByTestId("row-snow").filter({ hasText: "Good morning. Ready when you are." }),
    ).toBeVisible();
    await expect(word).toHaveText("Thinking");

    // The hub saw a hud hello with the token and the renderer never got a bridge beyond hubInfo and the window-chrome functions.
    expect(hub.received[0]).toMatchObject({ kind: "hello", role: "hud", token: hub.token });
    expect(await win.evaluate(() => Object.keys(window.snow))).toEqual(["hubInfo", "chrome"]);
    expect(await win.evaluate(() => Object.keys(window.snow.chrome))).toEqual([
      "hover",
      "click",
      "drag",
      "dragEnd",
      "onVisibility",
      "onCommand",
      "sendState",
      "setIcon",
    ]);
    expect(await win.evaluate(() => typeof (window as { require?: unknown }).require)).toBe(
      "undefined",
    );
  } finally {
    await app.close();
    await hub.close();
  }
});

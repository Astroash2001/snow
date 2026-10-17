// State the orb reads every frame but React must never see: audio levels arrive about 31 times a
// second, so ws.ts writes them here instead of into the store (re-rendering at that rate would eat
// the 100 ms budget). The render loop reads this object directly.
export interface Levels {
  mic: number;
  tts: number;
  /** performance.now() of the last write; a stale level reads as silence. */
  updatedAt: number;
}

export const levels: Levels = { mic: 0, tts: 0, updatedAt: 0 };

export function setLevel(
  channel: "mic" | "tts",
  level: number,
  now: number = performance.now(),
): void {
  levels[channel] = Math.min(1, Math.max(0, level));
  levels.updatedAt = now;
}

// The hub sends a level about every 32 ms; no update for this long means the voice has stopped.
export const LEVEL_STALE_MS = 200;

// Set only when the main process added ?snowtest=1 (it does that only under SNOW_HUD_TEST=1).
// Gates the perf marks and the window.__snowTest hook; both are absent in normal runs.
export const TEST_MODE: boolean =
  typeof location !== "undefined" && new URLSearchParams(location.search).get("snowtest") === "1";

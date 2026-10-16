import { readFileSync } from "node:fs";
import { join } from "node:path";

export interface HubInfo {
  url: string;
  token: string;
}

// Re-read on every call: a restarted hub has a new port and token.
export function getHubInfo(): HubInfo | null {
  const { SNOW_HUB_URL, SNOW_TOKEN, SNOW_DATA_DIR, LOCALAPPDATA } = process.env;
  if (SNOW_HUB_URL && SNOW_TOKEN) return { url: SNOW_HUB_URL, token: SNOW_TOKEN };
  const dataDir = SNOW_DATA_DIR || (LOCALAPPDATA ? join(LOCALAPPDATA, "Snow") : null);
  if (!dataDir) return null;
  try {
    const hub = JSON.parse(readFileSync(join(dataDir, "run", "hub.json"), "utf8"));
    if (typeof hub.port !== "number" || typeof hub.token !== "string") return null;
    return { url: `ws://127.0.0.1:${hub.port}`, token: hub.token };
  } catch {
    return null; // hub not running yet
  }
}

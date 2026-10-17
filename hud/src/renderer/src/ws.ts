import type { Hello } from "../../generated/contracts";
import { setLevel, TEST_MODE } from "./levels";
import { useHud, type WireMessage } from "./store";

// The bridge type lives in env.d.ts.

export const BACKOFF_MS = [500, 1000, 2000, 4000, 8000]; // the last step repeats
export const STABLE_AFTER_MS = 60_000; // online this long resets the backoff

// Keeps one hub socket alive: on every close it waits, re-reads hub.json through the bridge (a
// restarted hub has a new port and token) and connects again. The hub sends a full snapshot on
// every accepted hello, and the reducer replaces state from it, so nothing stale survives.
// Returns a function that stops reconnecting and closes the socket.
export function connectHub(): () => void {
  const { apply, setConnection } = useHud.getState();
  let stopped = false;
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let attempt = 0;

  const retryLater = () => {
    setConnection("offline");
    if (stopped) return;
    timer = setTimeout(open, BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]);
    attempt += 1;
  };

  async function open() {
    const info = await window.snow.hubInfo();
    if (stopped) return;
    if (!info) return retryLater();
    const ws = new WebSocket(info.url);
    socket = ws;
    let openedAt = 0;
    ws.onopen = () => {
      openedAt = Date.now();
      const hello: Hello = { kind: "hello", role: "hud", token: info.token, protocol: 1 };
      ws.send(JSON.stringify(hello));
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(String(ev.data)) as WireMessage;
        if ("event" in msg) {
          // About 31 levels a second go to a ref the orb reads, never through React state.
          if (msg.event.type === "audio.level") return setLevel(msg.event.channel, msg.event.level);
          // Perf marks for the event-to-paint budget (HUD-03); only in test runs.
          if (TEST_MODE && msg.event.type === "presence.state") {
            performance.mark(`evt:${msg.event.seq}`);
          }
        }
        apply(msg);
      } catch {
        // A frame that is not JSON is ignored; the hub only sends valid frames.
      }
    };
    ws.onclose = () => {
      if (socket !== ws) return;
      if (openedAt && Date.now() - openedAt >= STABLE_AFTER_MS) attempt = 0;
      retryLater();
    };
  }

  void open();
  return () => {
    stopped = true;
    clearTimeout(timer);
    socket?.close();
  };
}

import type { Hello } from "../../generated/contracts";
import { useHud, type WireMessage } from "./store";

declare global {
  interface Window {
    snow: { hubInfo: () => Promise<{ url: string; token: string } | null> };
  }
}

// Opens the hub socket once. Reconnect with backoff is plan 01-15; until then a close means offline.
export async function connectHub(): Promise<WebSocket | null> {
  const { apply, setConnection } = useHud.getState();
  const info = await window.snow.hubInfo();
  if (!info) {
    setConnection("offline");
    return null;
  }
  const ws = new WebSocket(info.url);
  ws.onopen = () => {
    const hello: Hello = { kind: "hello", role: "hud", token: info.token, protocol: 1 };
    ws.send(JSON.stringify(hello));
  };
  ws.onmessage = (ev) => {
    try {
      apply(JSON.parse(String(ev.data)) as WireMessage);
    } catch {
      // A frame that is not JSON is ignored; the hub only sends valid frames.
    }
  };
  ws.onclose = () => setConnection("offline");
  return ws;
}

import { contextBridge, ipcRenderer } from "electron";

const finite = (n: unknown, limit = 10_000): n is number =>
  typeof n === "number" && Number.isFinite(n) && Math.abs(n) <= limit;
const DATA_URL = /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/;

// Subscribes to a main-to-renderer channel and returns the unsubscribe function.
function listen<T>(channel: string, accept: (v: unknown) => v is T, cb: (v: T) => void) {
  const handler = (_e: unknown, v: unknown) => {
    if (accept(v)) cb(v);
  };
  ipcRenderer.on(channel, handler);
  return () => {
    ipcRenderer.removeListener(channel, handler);
  };
}

// Window chrome only, no data: HUD data stays on the WebSocket. Every argument is validated here
// and again in main (T-01-39).
const chrome = {
  /** Mini window: the pointer entered (true) or left (false) the orb. */
  hover: (over: boolean) => {
    if (typeof over === "boolean") ipcRenderer.send("mini:hover", over);
  },
  /** Mini window: the orb was clicked. */
  click: () => ipcRenderer.send("mini:click"),
  /** Mini window drag by screen deltas (wired by plan 01-27). */
  drag: (dx: number, dy: number) => {
    if (finite(dx) && finite(dy)) ipcRenderer.send("mini:drag", dx, dy);
  },
  dragEnd: () => ipcRenderer.send("mini:dragEnd"),
  /** Dashboard shown (true) or hidden (false); it renders nothing while hidden. */
  onVisibility: (cb: (visible: boolean) => void) =>
    listen("chrome:visibility", (v): v is boolean => typeof v === "boolean", cb),
  /** A tray or menu action for the dashboard renderer to carry out (wired by plan 01-27). */
  onCommand: (cb: (command: string) => void) =>
    listen("chrome:command", (v): v is string => typeof v === "string" && v.length < 32, cb),
  /** What the tray needs to show: the state word and whether mute or a fault is on. */
  sendState: (state: { stateWord: string; muted: boolean; attention: boolean }) => {
    if (
      typeof state?.stateWord === "string" &&
      state.stateWord.length < 64 &&
      typeof state.muted === "boolean" &&
      typeof state.attention === "boolean"
    ) {
      ipcRenderer.send("chrome:state", {
        stateWord: state.stateWord,
        muted: state.muted,
        attention: state.attention,
      });
    }
  },
  /** A rendered orb icon for the tray and the window (a PNG data URL). */
  setIcon: (dataUrl: string) => {
    if (typeof dataUrl === "string" && dataUrl.length < 200_000 && DATA_URL.test(dataUrl)) {
      ipcRenderer.send("chrome:icon", dataUrl);
    }
  },
};

contextBridge.exposeInMainWorld("snow", {
  // Where the hub is and the token for it.
  hubInfo: () => ipcRenderer.invoke("hub:info"),
  chrome,
});

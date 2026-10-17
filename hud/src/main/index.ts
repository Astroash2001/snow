import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { app, ipcMain, Menu, type NativeImage, nativeImage, nativeTheme } from "electron";
import { getHubInfo } from "./hubinfo";
import {
  type ChromeState,
  createTray,
  INITIAL_STATE,
  type MenuAction,
  menuTemplate,
  type SnowTray,
} from "./tray";
import { WindowManager } from "./windows";

nativeTheme.themeSource = "dark";

const TEST = process.env.SNOW_HUD_TEST === "1";
// Only the e2e suite may move the user-data directory: it keeps test runs out of the real
// instance lock and the real remembered mini position. A spec can name its own directory; the
// rest share one fixed scratch directory (runs are sequential, so the lock never collides).
if (TEST) {
  app.setPath(
    "userData",
    process.env.SNOW_HUD_USER_DATA || join(tmpdir(), "snow-hud-test-default"),
  );
}

/** After Quit, how long to wait for the core to close the socket before quitting anyway. */
const QUIT_GRACE_MS = 3000;

// The hub passes --autostart at logon and --restarted when its supervisor relaunches the HUD
// (plan 01-14): both show only the mini indicator. A manual launch shows the dashboard.
const quiet = process.argv.includes("--autostart") || process.argv.includes("--restarted");

let state: ChromeState = INITIAL_STATE;
let tray: SnowTray | null = null;
let quitTimer: NodeJS.Timeout | null = null;
const icons = new Map<number, NativeImage>();

// Menu actions never talk to the core themselves: the dashboard renderer owns the one socket, so
// mute and quit travel to it as commands and leave as cmd.mute.set (by "tray") and cmd.app.quit.
function run(action: MenuAction): void {
  if (action === "open") windows.openDashboard();
  else if (action === "quit") requestQuit();
  else windows.sendCommand(action);
}

function requestQuit(): void {
  if (quitTimer) return;
  // Online, the core stops every subsystem and exits; the socket closing (see onState) or the
  // grace period ends our wait. Offline there is nothing to wait for.
  windows.sendCommand("quit");
  quitTimer = setTimeout(() => app.quit(), state.online ? QUIT_GRACE_MS : 0);
}

const template = () => menuTemplate(state, run);

const windows = new WindowManager({
  quiet,
  positionFile: join(app.getPath("userData"), "mini-position.json"),
  miniMenu: () => Menu.buildFromTemplate(template()),
});

// The preload checks this too; main does not trust it (T-01-39).
function isChromeState(v: unknown): v is ChromeState {
  const s = v as Partial<ChromeState> | null;
  return (
    typeof s?.stateWord === "string" &&
    s.stateWord.length < 64 &&
    typeof s.muted === "boolean" &&
    typeof s.attention === "boolean" &&
    typeof s.online === "boolean"
  );
}

function onState(next: ChromeState): void {
  state = next;
  tray?.update(state);
  // Quit was asked while online and the core has now gone: nothing left to wait for.
  if (quitTimer && !state.online) app.quit();
}

// The dashboard renders the orb icons (16 and 32 px, one message each); the tray gets both sizes
// so it can pick for the display scale, and the windows get the larger one.
function onIcon(dataUrl: string): void {
  const image = nativeImage.createFromDataURL(dataUrl);
  if (image.isEmpty()) return;
  icons.set(image.getSize().width, image);
  const small = icons.get(16);
  const large = icons.get(32);
  const icon = nativeImage.createEmpty();
  if (small) icon.addRepresentation({ scaleFactor: 1, buffer: small.toPNG() });
  if (large) icon.addRepresentation({ scaleFactor: 2, buffer: large.toPNG() });
  tray?.setIcon(icon);
  windows.setIcon(large ?? icon);
}

if (!app.requestSingleInstanceLock()) {
  // Another Snow is already running: it shows its dashboard (below) and this one leaves.
  app.quit();
} else {
  app.on("second-instance", () => windows.openDashboard());
  app.whenReady().then(() => {
    ipcMain.handle("hub:info", () => getHubInfo());
    // Tray state and icons are the dashboard renderer's to send; nothing else may set them.
    ipcMain.on("chrome:state", (e, next: unknown) => {
      if (windows.isDashboard(e.sender) && isChromeState(next)) onState(next);
    });
    ipcMain.on("chrome:icon", (e, dataUrl: unknown) => {
      if (windows.isDashboard(e.sender) && typeof dataUrl === "string") onIcon(dataUrl);
    });
    windows.start();
    tray = createTray(
      () => windows.openDashboard(),
      (s) => menuTemplate(s, run),
    );
    tray.update(state);
    app.on("will-quit", () => tray?.destroy());
    if (TEST) exposeTestHook();
  });
}

// Test-only (SNOW_HUD_TEST=1): reaches the tray and menu handlers without a real click, so the
// e2e suite never opens a native menu. It holds no data and sends nothing by itself.
function exposeTestHook(): void {
  const items = () => template().filter((i) => i.type !== "separator");
  (globalThis as Record<string, unknown>).__snowChrome = {
    state: () => state,
    tooltip: () => tray?.tooltip() ?? "",
    menuLabels: () => items().map((i) => ({ label: i.label, enabled: i.enabled !== false })),
    clickMenu: (label: string) => {
      const item = items().find((i) => i.label === label);
      if (!item || item.enabled === false) return false;
      (item.click as unknown as () => void)();
      return true;
    },
    clickTray: () => tray?.click(),
    iconSizes: () => [...icons.keys()].sort((a, b) => a - b),
    // A fingerprint of the large icon, to tell one state's icon from another.
    iconHash: () => {
      const large = icons.get(32);
      return large ? createHash("sha1").update(large.toPNG()).digest("hex") : null;
    },
  };
}

// The dashboard and the mini indicator trade places; closing the dashboard must not quit Snow.
// Quit happens only through Quit Snow in the tray or the mini orb's menu.

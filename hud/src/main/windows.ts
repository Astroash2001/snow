import { join } from "node:path";
import { app, BrowserWindow, ipcMain, screen } from "electron";

const MINI_W = 320;
const MINI_H = 56;
const MINI_MARGIN = 16;

// SNOW_HUD_TEST=1 (set only by the e2e suite) makes each renderer expose its test hook.
const testQuery = (): Record<string, string> | undefined =>
  process.env.SNOW_HUD_TEST === "1" ? { snowtest: "1" } : undefined;

const webPreferences = () => ({
  preload: join(__dirname, "../preload/index.js"),
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
});

// A renderer only ever shows the one page it was loaded with: no navigation, no new windows.
function lockDown(win: BrowserWindow): void {
  win.webContents.on("will-navigate", (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
}

// Owns the two forms of Snow's window (D-11): the dashboard and the mini indicator. Exactly one of
// them is visible at any time. The mini window is created the first time it is needed.
export class WindowManager {
  private dashboard: BrowserWindow | null = null;
  private mini: BrowserWindow | null = null;
  private miniWanted = false;
  private quitting = false;
  // What the dashboard renderer was last told; a page that loads while hidden is told again.
  private dashboardHidden = false;

  start(): void {
    app.on("before-quit", () => {
      this.quitting = true;
    });
    this.registerIpc();
    this.createDashboard();
  }

  /** Shows and focuses the dashboard and hides the mini indicator. */
  openDashboard(): void {
    const win = this.dashboard;
    if (!win || win.isDestroyed()) return;
    this.miniWanted = false;
    if (this.mini && !this.mini.isDestroyed()) {
      // A hidden window gets no pointerleave: put click-through back before it goes.
      this.mini.setIgnoreMouseEvents(true, { forward: true });
      this.mini.hide();
    }
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
    this.sendVisibility(true);
  }

  /** Hides the dashboard (it renders nothing while hidden) and shows the mini indicator. */
  hideDashboard(): void {
    this.sendVisibility(false);
    this.dashboard?.hide();
    this.showMini();
  }

  showMini(): void {
    this.miniWanted = true;
    if (!this.mini || this.mini.isDestroyed()) this.createMini();
    else this.mini.showInactive();
  }

  private sendVisibility(visible: boolean): void {
    this.dashboardHidden = !visible;
    const wc = this.dashboard?.webContents;
    if (wc && !wc.isDestroyed()) wc.send("chrome:visibility", visible);
  }

  private createDashboard(): void {
    const win = new BrowserWindow({
      width: 960,
      height: 640,
      minWidth: 800,
      minHeight: 560,
      backgroundColor: "#0B0E14",
      title: "Snow",
      show: false,
      webPreferences: webPreferences(),
    });
    this.dashboard = win;
    lockDown(win);
    win.once("ready-to-show", () => win.show());
    // Close (X) and minimize do the same thing: Snow keeps running behind the mini indicator.
    win.on("close", (e) => {
      if (this.quitting) return;
      e.preventDefault();
      this.hideDashboard();
    });
    win.on("minimize", () => this.hideDashboard());
    // A renderer that loads while the dashboard is hidden must start out not rendering.
    win.webContents.on("did-finish-load", () => {
      if (this.dashboardHidden) this.sendVisibility(false);
    });
    win.loadFile(join(__dirname, "../renderer/index.html"), { query: testQuery() });
  }

  private createMini(): void {
    const work = screen.getPrimaryDisplay().workArea;
    const win = new BrowserWindow({
      width: MINI_W,
      height: MINI_H,
      x: work.x + work.width - MINI_W - MINI_MARGIN,
      y: work.y + MINI_MARGIN,
      frame: false,
      transparent: true,
      hasShadow: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      focusable: false,
      resizable: false,
      show: false,
      title: "Snow mini",
      webPreferences: webPreferences(),
    });
    this.mini = win;
    lockDown(win);
    // Floating, not screen-saver: it must not sit over fullscreen games.
    win.setAlwaysOnTop(true, "floating");
    // Click-through everywhere; the renderer turns it off only while the pointer is on the orb.
    win.setIgnoreMouseEvents(true, { forward: true });
    win.once("ready-to-show", () => {
      if (this.miniWanted) win.showInactive();
    });
    win.on("closed", () => {
      this.mini = null;
    });
    win.loadFile(join(__dirname, "../renderer/mini.html"), { query: testQuery() });
  }

  // Chrome-only channels (T-01-39): each one checks which window it came from and validates its
  // argument; nothing carries data.
  private registerIpc(): void {
    const fromMini = (sender: Electron.WebContents): boolean =>
      this.mini !== null && !this.mini.isDestroyed() && sender.id === this.mini.webContents.id;

    ipcMain.on("mini:hover", (e, over: unknown) => {
      if (!fromMini(e.sender) || typeof over !== "boolean") return;
      if (over) this.mini?.setIgnoreMouseEvents(false);
      else this.mini?.setIgnoreMouseEvents(true, { forward: true });
    });
    ipcMain.on("mini:click", (e) => {
      if (fromMini(e.sender)) this.openDashboard();
    });
  }
}

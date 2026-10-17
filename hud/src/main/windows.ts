import { join } from "node:path";
import { app, BrowserWindow, ipcMain, type Menu, type NativeImage, screen } from "electron";
import {
  clampToWorkArea,
  type DisplayInfo,
  loadPosition,
  MINI_H,
  MINI_W,
  onLeftHalf,
  type Point,
  type SavedPosition,
  savePosition,
} from "./position";

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

const toInfo = (d: Electron.Display): DisplayInfo => ({ id: d.id, workArea: d.workArea });
const finite = (n: unknown): n is number =>
  typeof n === "number" && Number.isFinite(n) && Math.abs(n) <= 20_000;

export interface WindowManagerOptions {
  /** Launched at logon or after a supervisor restart: only the mini indicator shows (CORE-01). */
  quiet: boolean;
  /** Where the mini window's position is remembered. */
  positionFile: string;
  /** The native menu for a right click on the mini orb. */
  miniMenu: () => Menu;
}

// Owns the two forms of Snow's window (D-11): the dashboard and the mini indicator. Exactly one of
// them is visible at any time. The mini window is created the first time it is needed.
export class WindowManager {
  private dashboard: BrowserWindow | null = null;
  private mini: BrowserWindow | null = null;
  private miniWanted = false;
  private quitting = false;
  // What the dashboard renderer was last told; a page that loads while hidden is told again.
  private dashboardHidden: boolean;
  // Where the mini window was last put, and the page's last-told side of its display.
  private miniPos: SavedPosition | null;
  private side: "left" | "right" | null = null;
  // The window origin when the current drag began; null when no drag is under way.
  private dragFrom: Point | null = null;
  private icon: NativeImage | null = null;

  constructor(private readonly opts: WindowManagerOptions) {
    this.dashboardHidden = opts.quiet;
    this.miniPos = loadPosition(opts.positionFile);
  }

  start(): void {
    app.on("before-quit", () => {
      this.quitting = true;
    });
    this.registerIpc();
    screen.on("display-removed", this.onDisplays);
    screen.on("display-metrics-changed", this.onDisplays);
    this.createDashboard();
    if (this.opts.quiet) this.showMini();
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

  /** Tells the dashboard renderer something to do (a tray or menu action). */
  sendCommand(command: string): void {
    const wc = this.dashboard?.webContents;
    if (wc && !wc.isDestroyed()) wc.send("chrome:command", command);
  }

  isDashboard(sender: Electron.WebContents): boolean {
    return this.dashboard !== null && !this.dashboard.isDestroyed()
      ? sender.id === this.dashboard.webContents.id
      : false;
  }

  /** The orb icon for the window title bars and the task switcher (D-31). */
  setIcon(icon: NativeImage): void {
    this.icon = icon;
    for (const win of [this.dashboard, this.mini]) if (win && !win.isDestroyed()) win.setIcon(icon);
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
    // A quiet launch keeps the dashboard hidden until the mini orb or the tray opens it.
    win.once("ready-to-show", () => {
      if (!this.dashboardHidden) win.show();
    });
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
    const origin = this.origin();
    const win = new BrowserWindow({
      width: MINI_W,
      height: MINI_H,
      x: origin.x,
      y: origin.y,
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
    if (this.icon) win.setIcon(this.icon);
    // Floating, not screen-saver: it must not sit over fullscreen games.
    win.setAlwaysOnTop(true, "floating");
    // Click-through everywhere; the renderer turns it off only while the pointer is on the orb.
    win.setIgnoreMouseEvents(true, { forward: true });
    // Created on a display with a different scale than the primary, a window can come out the
    // wrong size: set the bounds again now that it is there.
    this.settle(origin);
    win.once("ready-to-show", () => {
      if (this.miniWanted) win.showInactive();
    });
    win.webContents.on("did-finish-load", () => {
      this.side = null;
      this.sendSide(origin);
    });
    win.webContents.on("context-menu", () => this.opts.miniMenu().popup({ window: win }));
    win.on("closed", () => {
      this.mini = null;
    });
    win.loadFile(join(__dirname, "../renderer/mini.html"), { query: testQuery() });
  }

  private displays(): DisplayInfo[] {
    return screen.getAllDisplays().map(toInfo);
  }

  // Where the mini window belongs now: the remembered spot clamped into a visible work area, or the
  // default top-right corner when there is none or its display is gone.
  private origin(): Point {
    return clampToWorkArea(this.miniPos, this.displays(), toInfo(screen.getPrimaryDisplay()));
  }

  private displayAt(pos: Point): DisplayInfo {
    return toInfo(screen.getDisplayMatching({ x: pos.x, y: pos.y, width: MINI_W, height: MINI_H }));
  }

  // Always the same size: setBounds (not setPosition) so a move across displays of different scale
  // cannot stretch the window.
  private place(pos: Point): void {
    this.mini?.setBounds({
      x: Math.round(pos.x),
      y: Math.round(pos.y),
      width: MINI_W,
      height: MINI_H,
    });
    this.sendSide(pos);
  }

  /** Puts the mini window at `pos` and remembers it (in memory; a drag end also saves it). */
  private settle(pos: Point): SavedPosition {
    this.place(pos);
    this.miniPos = { x: pos.x, y: pos.y, displayId: this.displayAt(pos).id };
    return this.miniPos;
  }

  // The row mirrors on the left half of the display; the page is told only when that changes.
  private sendSide(pos: Point): void {
    const side = onLeftHalf(pos, this.displayAt(pos)) ? "left" : "right";
    if (side === this.side) return;
    this.side = side;
    const wc = this.mini?.webContents;
    if (wc && !wc.isDestroyed()) wc.send("chrome:command", `side:${side}`);
  }

  private readonly onDisplays = (): void => {
    if (this.mini && !this.mini.isDestroyed()) this.settle(this.origin());
  };

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
    // The renderer sends the pointer's total screen movement since the press; the window origin at
    // the first message is the anchor, so no message depends on the one before it.
    ipcMain.on("mini:drag", (e, dx: unknown, dy: unknown) => {
      if (!fromMini(e.sender) || !finite(dx) || !finite(dy) || !this.mini) return;
      const b = this.mini.getBounds();
      this.dragFrom ??= { x: b.x, y: b.y };
      this.place({ x: this.dragFrom.x + dx, y: this.dragFrom.y + dy });
    });
    ipcMain.on("mini:dragEnd", (e) => {
      if (!fromMini(e.sender) || !this.dragFrom || !this.mini) return;
      this.dragFrom = null;
      const b = this.mini.getBounds();
      // Dropped half off a screen edge: snap back inside that display, then remember it.
      const here = { x: b.x, y: b.y, displayId: this.displayAt(b).id };
      const pos = clampToWorkArea(here, this.displays(), toInfo(screen.getPrimaryDisplay()));
      savePosition(this.opts.positionFile, this.settle(pos));
    });
  }
}

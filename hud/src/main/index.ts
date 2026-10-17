import { join } from "node:path";
import { app, BrowserWindow, ipcMain, nativeTheme } from "electron";
import { getHubInfo } from "./hubinfo";

nativeTheme.themeSource = "dark";

function createDashboard(): void {
  const win = new BrowserWindow({
    width: 960,
    height: 640,
    minWidth: 800,
    minHeight: 560,
    backgroundColor: "#0B0E14",
    title: "Snow",
    show: false,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  // The renderer only ever shows the one page it was loaded with: no navigation, no new windows.
  win.webContents.on("will-navigate", (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.once("ready-to-show", () => win.show());
  // SNOW_HUD_TEST=1 (set only by the e2e suite) makes the renderer expose its test hook.
  const query = process.env.SNOW_HUD_TEST === "1" ? { snowtest: "1" } : undefined;
  win.loadFile(join(__dirname, "../renderer/index.html"), { query });
}

app.whenReady().then(() => {
  ipcMain.handle("hub:info", () => getHubInfo());
  createDashboard();
});

app.on("window-all-closed", () => app.quit());

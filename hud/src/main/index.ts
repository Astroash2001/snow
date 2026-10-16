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
  win.once("ready-to-show", () => win.show());
  win.loadFile(join(__dirname, "../renderer/index.html"));
}

app.whenReady().then(() => {
  ipcMain.handle("hub:info", () => getHubInfo());
  createDashboard();
});

app.on("window-all-closed", () => app.quit());

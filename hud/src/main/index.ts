import { app, ipcMain, nativeTheme } from "electron";
import { getHubInfo } from "./hubinfo";
import { WindowManager } from "./windows";

nativeTheme.themeSource = "dark";

const windows = new WindowManager();

app.whenReady().then(() => {
  ipcMain.handle("hub:info", () => getHubInfo());
  windows.start();
});

// The dashboard and the mini indicator trade places; closing the dashboard must not quit Snow.
// Quit happens only through app.quit() (the tray and mini menu, plan 01-27).

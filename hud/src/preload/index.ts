import { contextBridge, ipcRenderer } from "electron";

// The only thing the renderer gets from Electron: where the hub is and the token for it.
contextBridge.exposeInMainWorld("snow", {
  hubInfo: () => ipcRenderer.invoke("hub:info"),
});

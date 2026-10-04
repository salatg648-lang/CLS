const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("cls", {
  call: (method, params = {}) =>
    ipcRenderer.invoke("cls:call", { method, params }),
  choosePath: (kind) => ipcRenderer.invoke("cls:choose-path", kind),
  window: (action) => ipcRenderer.invoke("cls:window", action),
  platform: process.platform,
});
 
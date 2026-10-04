const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  protocol,
  net,
  clipboard,
  Menu,
} = require("electron");
const path = require("node:path");
const { mkdirSync } = require("node:fs");
const { pathToFileURL } = require("node:url");
const { PythonBridge } = require("./bridge.cjs");
protocol.registerSchemesAsPrivileged([
  {
    scheme: "cls",
    privileges: { standard: true, secure: true, supportFetchAPI: true },
  },
]);
let window,
  bridge,
  closing = false;
const development = !app.isPackaged;
const devURL = "http://localhost:5173";
function trusted(event) {
  const url = event.senderFrame?.url || "";
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame ||
    !(development
      ? new URL(url).origin === devURL
      : url.startsWith("cls://app/"))
  )
    throw new Error("Nicht erlaubter Desktop-Aufruf.");
}
app
  .whenReady()
  .then(async () => {
    const root = path.resolve(__dirname, "../..");
    mkdirSync(app.getPath("userData"), { recursive: true });
    bridge = new PythonBridge(
      app.isPackaged
        ? {
            command: path.join(
              process.resourcesPath,
              "cls-core",
              process.platform === "win32" ? "cls-core.exe" : "cls-core",
            ),
            args: [
              "--data-dir",
              path.resolve(
                process.argv
                  .find((arg) => arg.startsWith("--data-dir="))
                  ?.slice(11) || path.join(app.getPath("userData"), "data"),
              ),
            ],
            cwd: app.getPath("userData"),
            clipboard,
          }
        : {
            command:
              process.env.CLS_PYTHON ||
              (process.platform === "win32" ? "python" : "python3"),
            args: [
              "-m",
              "desktop.bridge",
              ...(process.env.CLS_DATA_DIR
                ? ["--data-dir", process.env.CLS_DATA_DIR]
                : []),
            ],
            cwd: root,
            clipboard,
          },
    );
    protocol.handle("cls", (request) => {
      const url = new URL(request.url);
      const relative =
        decodeURIComponent(url.pathname).replace(/^\/+/, "") || "index.html";
      const base = path.resolve(__dirname, "../dist"),
        file = path.resolve(base, relative);
      if (url.hostname !== "app" || !file.startsWith(base + path.sep))
        return new Response("Forbidden", { status: 403 });
      return net.fetch(pathToFileURL(file).href);
    });
    window = new BrowserWindow({
      width: 1440,
      height: 960,
      minWidth: 1000,
      minHeight: 700,
      backgroundColor: "#151719",
      title: "CLS",
      frame: false,
      show: false,
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
        webSecurity: true,
      },
    });
    Menu.setApplicationMenu(null);
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (event) => event.preventDefault());
    window.webContents.session.setPermissionRequestHandler(
      (_contents, _permission, callback) => callback(false),
    );
    window.webContents.session.webRequest.onHeadersReceived(
      (details, callback) => {
        callback({
          responseHeaders: {
            ...details.responseHeaders,
            "Content-Security-Policy": [
              development
                ? "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws://localhost:5173; object-src 'none'; base-uri 'none'"
                : "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-src 'none'",
            ],
          },
        });
      },
    );
    ipcMain.handle("cls:call", (event, { method, params }) => {
      trusted(event);
      return bridge.call(method, params);
    });
    ipcMain.handle("cls:choose-path", async (event, kind) => {
      trusted(event);
      if (!["directory", "document"].includes(kind))
        throw new Error("Ungültiger Dialog.");
      const result = await dialog.showOpenDialog(window, {
        properties: [kind === "directory" ? "openDirectory" : "openFile"],
      });
      return result.canceled ? null : result.filePaths[0];
    });
    ipcMain.handle("cls:window", (event, action) => {
      trusted(event);
      if (action === "minimize") window.minimize();
      else if (action === "maximize")
        window.isMaximized() ? window.unmaximize() : window.maximize();
      else if (action === "close") window.close();
    });
    window.on("close", async (event) => {
      if (closing) return;
      event.preventDefault();
      const { response } = await dialog.showMessageBox(window, {
        type: "question",
        title: "CLS beenden",
        message: "CLS beenden?",
        detail:
          "Laufende Aktionen werden noch abgeschlossen. Änderungen bleiben erhalten.",
        buttons: ["Zurück", "Beenden"],
        defaultId: 0,
        cancelId: 0,
      });
      if (response !== 1) return;
      closing = true;
      window.setTitle("CLS wird beendet …");
      await bridge.close();
      window.destroy();
      app.quit();
    });
    window.once("ready-to-show", () => window.show());
    await window.loadURL(development ? devURL : "cls://app/index.html");
  })
  .catch(() => {
    dialog.showErrorBox(
      "CLS konnte nicht starten",
      "Installation und Python-Core prüfen.",
    );
    app.quit();
  });
app.on("window-all-closed", () => app.quit());

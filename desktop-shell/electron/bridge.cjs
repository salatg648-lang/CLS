const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const { randomUUID } = require("node:crypto");

class PythonBridge {
  constructor({ command, args, cwd, clipboard }) {
    this.pending = new Map();
    this.closed = false;
    this.child = spawn(command, args, {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
    });
    this.ready = new Promise((resolve, reject) => {
      const timer = setTimeout(
        () =>
          reject(
            new Error("CLS-Core startet nicht. Python/Installation prüfen."),
          ),
        30000,
      );
      this.markReady = () => {
        clearTimeout(timer);
        resolve();
      };
      this.rejectReady = () => {
        clearTimeout(timer);
        reject(new Error("CLS-Core konnte nicht gestartet werden."));
      };
    });
    this.ready.catch(() => {});
    // Never forward stderr (which can include project data) into renderer/browser logs.
    this.child.stderr.on("data", () => {});
    createInterface({ input: this.child.stdout }).on("line", async (line) => {
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        return;
      }
      if (message.event === "ready") return this.markReady();
      if (message.event === "clipboard") {
        let result = null,
          error;
        try {
          if (!clipboard) throw new Error("Clipboard unavailable");
          if (message.operation === "read") result = clipboard.readText();
          else if (
            message.operation === "write" &&
            typeof message.content === "string" &&
            Buffer.byteLength(message.content) <= 1000000
          )
            clipboard.writeText(message.content);
          else throw new Error("Invalid clipboard operation");
        } catch {
          error = "Clipboard nicht verfügbar.";
        }
        return this.send({
          kind: "clipboard_result",
          id: message.id,
          result,
          error,
        });
      }
      const pending = this.pending.get(message.id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(message.id);
      message.error
        ? pending.reject(new Error(message.error))
        : pending.resolve(message.result);
    });
    const fail = () => {
      this.closed = true;
      this.rejectReady();
      for (const { reject, timer } of this.pending.values()) {
        clearTimeout(timer);
        reject(
          new Error(
            "Verbindung zum CLS-Core beendet. Bereits gestartete Aktionen vor Wiederholung prüfen.",
          ),
        );
      }
      this.pending.clear();
    };
    this.child.on("error", fail);
    this.child.on("exit", fail);
    this.child.stdin.on("error", fail);
    this.exited = new Promise((resolve) => this.child.once("exit", resolve));
  }
  send(value) {
    if (!this.closed) this.child.stdin.write(JSON.stringify(value) + "\n");
  }
  async call(method, params = {}) {
    await this.ready;
    if (this.closed) throw new Error("CLS-Core ist nicht verbunden.");
    if (this.pending.size >= 32) throw new Error("Zu viele laufende Aktionen.");
    if (
      typeof method !== "string" ||
      !params ||
      Array.isArray(params) ||
      typeof params !== "object"
    )
      throw new Error("Ungültige Anfrage.");
    const id = randomUUID(),
      payload = { id, method, params };
    if (Buffer.byteLength(JSON.stringify(payload)) > 1900000)
      throw new Error("Anfrage ist zu groß.");
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(
          new Error(
            "Antwortzeit überschritten. Ausführung kann noch laufen; Aktionsverlauf vor Wiederholung prüfen.",
          ),
        );
      }, 600000);
      this.pending.set(id, { resolve, reject, timer });
      this.send(payload);
    });
  }
  async close() {
    if (this.closed) return;
    this.send({ kind: "shutdown" });
    await this.exited;
  }
}
module.exports = { PythonBridge };

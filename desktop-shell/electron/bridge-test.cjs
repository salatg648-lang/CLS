const test = require("node:test");
const assert = require("node:assert/strict");
const { mkdtempSync, rmSync, readFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const { PythonBridge } = require("./bridge.cjs");

test(
  "real Python protocol: startup, isolated state, core actions, errors and shutdown",
  { timeout: 40000 },
  async () => {
    const directory = mkdtempSync(path.join(tmpdir(), "cls-transport-test-"));
    const bridge = new PythonBridge({
      command:
        process.env.CLS_PYTHON ||
        (process.platform === "win32" ? "python" : "python3"),
      args: ["-m", "desktop.bridge", "--demo", "--data-dir", directory],
      cwd: path.resolve(__dirname, "../.."),
    });
    try {
      const snapshot = await bridge.call("snapshot");
      assert.equal(snapshot.demo, true);
      assert.equal(snapshot.projects.length, 3);
      assert.ok(snapshot.providers.every((p) => !p.enabled));
      await assert.rejects(
        bridge.call("tools.execute", { name: "write_file" }),
        /nicht freigegeben/,
      );
      const task = await bridge.call("create_task", {
        goal: "Erstelle desktop-smoke.txt mit VERIFIED",
      });
      const pending = await bridge.call("run_task", { task_id: task.id });
      assert.equal(pending.status, "NEEDS_CONFIRMATION");
      const complete = await bridge.call("run_task", {
        task_id: task.id,
        approve: true,
        confirmation_id: pending.pending.confirmation_id,
      });
      assert.equal(complete.status, "COMPLETED");
      assert.equal(
        readFileSync(path.join(task.root, "desktop-smoke.txt"), "utf8"),
        "VERIFIED",
      );
      const blocked = await bridge.call("create_task", {
        goal: "Build ausführen",
      });
      const blockedResult = await bridge.call("run_task", {
        task_id: blocked.id,
      });
      assert.notEqual(blockedResult.status, "COMPLETED");
      await assert.rejects(
        bridge.call("configure_provider", { name: "ollama", enabled: true }),
        /nicht gespeichert/,
      );
    } finally {
      await bridge.close();
      rmSync(directory, { recursive: true, force: true });
    }
  },
);

test(
  "missing Python fails explicitly without a stuck request",
  { timeout: 5000 },
  async () => {
    const bridge = new PythonBridge({
      command: path.join(tmpdir(), "cls-nonexistent-python"),
      args: [],
      cwd: tmpdir(),
    });
    await assert.rejects(bridge.call("snapshot"), /nicht gestartet/);
  },
);

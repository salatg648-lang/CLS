// Runs against the packaged desktop, on an isolated X display and synthetic data.
import { spawn } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  rmSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import assert from "node:assert/strict";
const temp = mkdtempSync(path.join(tmpdir(), "cls-native-smoke-"));
const work = path.join(temp, "workspace");
mkdirSync(work);
const executable = path.resolve("release/linux-unpacked/cls-desktop");
const child = spawn(
  executable,
  [
    `--data-dir=${path.join(temp, "data")}`,
    `--user-data-dir=${path.join(temp, "chromium")}`,
    "--remote-debugging-port=9234",
  ],
  { stdio: ["ignore", "pipe", "pipe"] },
);
let logs = "";
child.stderr.on("data", (b) => (logs += b.toString()));
child.stdout.on("data", (b) => (logs += b.toString()));
const pending = new Map();
let socket,
  id = 0;
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
function rpc(method, params = {}) {
  return new Promise((resolve, reject) => {
    const rid = ++id;
    const timer = setTimeout(() => {
      pending.delete(rid);
      reject(Error(`CDP timeout: ${method}`));
    }, 25000);
    pending.set(rid, { resolve, reject, timer });
    socket.send(JSON.stringify({ id: rid, method, params }));
  });
}
async function evaluate(expression) {
  const value = await rpc("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (value.exceptionDetails)
    throw Error(JSON.stringify(value.exceptionDetails));
  return value.result.value;
}
try {
  let target;
  for (let i = 0; i < 150; i++) {
    try {
      const targets = await fetch("http://127.0.0.1:9234/json").then((r) =>
        r.json(),
      );
      target = targets.find((t) => t.type === "page");
      if (target) break;
    } catch {}
    if (child.exitCode !== null) throw Error("Desktop exited: " + logs);
    await pause(100);
  }
  if (!target) throw Error("Desktop CDP did not start: " + logs);
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const p = pending.get(message.id);
    if (p) {
      clearTimeout(p.timer);
      pending.delete(message.id);
      message.error
        ? p.reject(Error(message.error.message))
        : p.resolve(message.result);
    }
  });
  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (
      await evaluate(
        'Boolean(window.cls && document.querySelector(".app-shell"))',
      )
    ) {
      ready = true;
      break;
    }
    await pause(100);
  }
  if (!ready) throw Error("Desktop UI did not become ready: " + logs);
  assert.equal(await evaluate("location.origin"), "cls://app");
  assert.equal(await evaluate("typeof require"), "undefined");
  assert.equal(await evaluate("typeof process"), "undefined");
  assert.equal(await evaluate("typeof window.cls.call"), "function");
  const snapshot = await evaluate('window.cls.call("snapshot")');
  assert.equal(snapshot.demo, false);
  assert.equal(snapshot.tasks.length, 0);
  const project = await evaluate(
    `window.cls.call('create_project',${JSON.stringify({ name: "Native smoke", path: work })})`,
  );
  await evaluate(
    `window.cls.call('set_active_project',{project_id:${project.id}})`,
  );
  const task = await evaluate(
    `window.cls.call('create_task',${JSON.stringify({ goal: "Erstelle smoke.txt mit NATIVE", ai_policy: { mode: "NEVER" } })})`,
  );
  const waiting = await evaluate(
    `window.cls.call('run_task',{task_id:'${task.id}'})`,
  );
  assert.equal(waiting.status, "NEEDS_CONFIRMATION");
  const done = await evaluate(
    `window.cls.call('run_task',${JSON.stringify({ task_id: task.id, approve: true, confirmation_id: waiting.pending.confirmation_id })})`,
  );
  assert.equal(done.status, "COMPLETED");
  assert.equal(readFileSync(path.join(work, "smoke.txt"), "utf8"), "NATIVE");
  const clip = await evaluate(
    `window.cls.call('create_task',${JSON.stringify({ goal: 'Kopiere "Native clipboard" in die Zwischenablage', ai_policy: { mode: "NEVER" } })})`,
  );
  const cp = await evaluate(
    `window.cls.call('run_task',{task_id:'${clip.id}'})`,
  );
  const cd = await evaluate(
    `window.cls.call('run_task',${JSON.stringify({ task_id: clip.id, approve: true, confirmation_id: cp.pending.confirmation_id })})`,
  );
  assert.equal(cd.status, "COMPLETED");
  const read = await evaluate(
    `window.cls.call('create_task',${JSON.stringify({ goal: "Lies meinen Clipboard-Inhalt", ai_policy: { mode: "NEVER" } })})`,
  );
  const rd = await evaluate(
    `window.cls.call('run_task',{task_id:'${read.id}'})`,
  );
  assert.ok(rd.result.includes("Native clipboard"));
  const denied = await evaluate(
    `window.cls.call('tools.execute',{}).then(()=>false,()=>true)`,
  );
  assert.equal(denied, true);
  console.log(
    "PASS: packaged Electron custom origin, renderer isolation, Python bridge, verified write and native clipboard roundtrip",
  );
} finally {
  socket?.close();
  for (const p of pending.values()) {
    clearTimeout(p.timer);
    p.reject(Error("Smoke shutdown"));
  }
  child.kill("SIGKILL"); // All assertions finished; stop only this isolated smoke app.
  await new Promise((resolve) => {
    if (child.exitCode !== null) resolve();
    else child.once("exit", resolve);
  });
  rmSync(temp, {
    recursive: true,
    force: true,
    maxRetries: 10,
    retryDelay: 100,
  });
}

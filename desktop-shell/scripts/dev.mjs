import { spawn } from "node:child_process";
import { createServer } from "vite";
import electron from "electron";
const server = await createServer({
  server: { host: "localhost", port: 5173, strictPort: true },
});
await server.listen();
const child = spawn(electron, ["."], { stdio: "inherit", env: process.env });
child.on("exit", async (code) => {
  await server.close();
  process.exitCode = code || 0;
});

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
const require = createRequire(import.meta.url);
const { PythonBridge } = require("./electron/bridge.cjs");
const root = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig({
  base: "./",
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          ui: [
            "react",
            "react-dom",
            "@radix-ui/react-dialog",
            "@radix-ui/react-dropdown-menu",
            "cmdk",
          ],
          tables: ["@tanstack/react-table", "@tanstack/react-query"],
        },
      },
    },
  },
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "cls-isolated-preview",
      configureServer(server) {
        if (process.env.VITEST) return;
        const directory = mkdtempSync(path.join(tmpdir(), "cls-preview-"));
        const bridge = new PythonBridge({
          command: process.env.CLS_PYTHON || "python3",
          args: ["-m", "desktop.bridge", "--demo", "--data-dir", directory],
          cwd: root,
        });
        server.httpServer?.once("close", () => {
          void bridge.close();
        });
        server.middlewares.use("/__cls", async (req, res) => {
          res.setHeader("Content-Type", "application/json");
          res.setHeader("Cache-Control", "no-store");
          const origin = req.headers.origin;
          if (
            req.method !== "POST" ||
            req.headers["x-cls-client"] !== "preview" ||
            !req.headers["content-type"]?.startsWith("application/json") ||
            (origin && new URL(origin).host !== req.headers.host)
          ) {
            res.statusCode = 403;
            res.end(JSON.stringify({ error: "Unzulässige Vorschauanfrage." }));
            return;
          }
          try {
            let body = "";
            for await (const chunk of req) {
              body += chunk;
              if (Buffer.byteLength(body) > 1900000)
                throw new Error("Anfrage zu groß.");
            }
            const { method, params } = JSON.parse(body);
            res.end(
              JSON.stringify({ result: await bridge.call(method, params) }),
            );
          } catch (error) {
            res.statusCode = 400;
            res.end(
              JSON.stringify({
                error:
                  error instanceof Error
                    ? error.message
                    : "Anfrage fehlgeschlagen.",
              }),
            );
          }
        });
      },
    },
  ],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.tsx"],
  },
});

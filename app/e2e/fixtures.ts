// Harness of the GUI smoke tests: serves dist/, starts the real Python worker (`python -m propbench.worker`) and
// routes the UI's Tauri `invoke` calls to it over JSON-RPC, exactly as pb-engine does in the app. Desktop-only
// commands (file dialogs, project files, terminal) are emulated in memory.
import { type ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { test as base, expect, type Page } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(here, "..", "dist");
const workerDir = path.join(here, "..", "..", "worker");

function workerPython(): string {
  if (process.env.PB_WORKER_PYTHON) return process.env.PB_WORKER_PYTHON;
  const venv = path.join(workerDir, ".venv");
  return process.platform === "win32" ? path.join(venv, "Scripts", "python.exe") : path.join(venv, "bin", "python");
}

class Worker {
  private proc: ChildProcessWithoutNullStreams;
  private pending = new Map<number, (m: { result?: unknown; error?: { code: number; message: string } }) => void>();
  private next = 1;
  ready: Promise<void>;

  constructor(dataDir: string) {
    this.proc = spawn(workerPython(), ["-I", "-B", "-X", "utf8", "-m", "propbench.worker"], {
      env: { ...process.env, PB_COMPONENTS_DIR: path.join(dataDir, "components"), PB_ENVS_DIR: path.join(dataDir, "envs") },
    });
    this.proc.stderr.on("data", () => undefined);
    let resolve: () => void;
    this.ready = new Promise((r) => (resolve = r));
    createInterface({ input: this.proc.stdout }).on("line", (line) => {
      const m = JSON.parse(line);
      if (m.method === "ready") return resolve();
      const p = this.pending.get(m.id);
      this.pending.delete(m.id);
      p?.(m);
    });
  }

  call(method: string, params: unknown) {
    const id = this.next++;
    this.proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
    return new Promise<{ result?: unknown; error?: { code: number; message: string } }>((r) => this.pending.set(id, r));
  }

  stop() {
    this.proc.kill();
  }
}

function serve(): Promise<http.Server> {
  const types: Record<string, string> = { ".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml" };
  const server = http.createServer((req, res) => {
    let file = path.join(dist, decodeURIComponent((req.url ?? "/").split("?")[0]));
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, "index.html");
    if (!fs.existsSync(file)) {
      res.writeHead(404);
      res.end();
      return;
    }
    res.writeHead(200, { "content-type": types[path.extname(file)] ?? "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r(server)));
}

/** Answers the UI's Tauri commands: worker operations by the real worker, desktop-only ones in memory. */
async function connect(page: Page, worker: Worker) {
  const files = new Map<string, unknown>();
  page.on("pageerror", (e) => {
    throw e;
  });
  await page.exposeFunction("__pbInvoke", async (cmd: string, args: Record<string, unknown>) => {
    const ok = (result: unknown) => ({ result });
    switch (cmd) {
      case "property": {
        const m = await worker.call("property", args.request);
        return m.error ? { error: { kind: "property", message: m.error.message } } : ok(m.result);
      }
      case "worker": {
        const m = await worker.call(String(args.method), args.params ?? {});
        if (m.error) return { error: { kind: m.error.code === -32602 ? "invalid_input" : "propbench", message: m.error.message } };
        return ok(m.result);
      }
      case "project_save":
        files.set(String(args.path), args.project);
        return ok(args.project);
      case "project_open":
        return files.has(String(args.path)) ? ok(files.get(String(args.path))) : { error: { kind: "project", message: "not found" } };
      case "project_recover":
        return ok(null);
      case "plugin_list":
        return ok([]);
      case "plugin:dialog|save":
      case "plugin:dialog|open":
        return ok(path.join("/tmp", "propbench-e2e", "cf3i.pbp"));
      case "plugin:dialog|ask":
      case "plugin:dialog|confirm":
        return ok(true);
      default:
        return ok(null); // cancel, autosave, discard, terminal_*: nothing to do in the browser
    }
  });
  await page.addInitScript(() => {
    const w = window as unknown as Record<string, unknown>;
    w.__TAURI_INTERNALS__ = {
      invoke: async (cmd: string, args: Record<string, unknown>) => {
        const r = await (w.__pbInvoke as (c: string, a: unknown) => Promise<{ result?: unknown; error?: unknown }>)(cmd, args);
        if (r.error) throw r.error;
        return r.result;
      },
      transformCallback: () => 0,
    };
  });
}

export const test = base.extend<{ app: Page }>({
  app: async ({ page }, use, testInfo) => {
    const server = await serve();
    const worker = new Worker(testInfo.outputPath("appdata"));
    await worker.ready;
    await connect(page, worker);
    await page.goto(`http://127.0.0.1:${(server.address() as AddressInfo).port}/`);
    await use(page);
    worker.stop();
    server.close();
  },
});

export { expect };

export async function menu(page: Page, top: string, item: string | RegExp) {
  await page.getByRole("button", { name: top, exact: true }).first().click();
  await page.getByRole("menuitem", { name: item }).click();
}

/** Wait until no worker operation is running (the status-bar progress indicator is idle). */
export async function idle(page: Page) {
  await page.waitForFunction(() => !document.querySelector(".progress.running"), null, { timeout: 120_000 });
}

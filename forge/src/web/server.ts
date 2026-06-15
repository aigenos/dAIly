import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { readFile, readdir } from "node:fs/promises";
import { join, relative } from "node:path";
import { URL } from "node:url";
import type { ForgeConfig, PermissionMode } from "../config/config.js";
import { createProvider } from "../llm/factory.js";
import { userText } from "../llm/types.js";
import { PermissionChecker } from "../safety/permissions.js";
import { BASE_TOOLS } from "../tools/index.js";
import type { ToolContext } from "../tools/types.js";
import { Agent, type AgentEvents } from "../agent/agent.js";
import { INTERACTIVE_SYSTEM } from "../orchestrator/roles.js";
import { Orchestrator, type TeamEvents } from "../orchestrator/orchestrator.js";
import { PAGE } from "./page.js";
import { banner, info } from "../cli/render.js";

const SKIP = new Set(["node_modules", ".git", "dist", ".forge"]);

export function startServer(cfg: ForgeConfig, port: number): void {
  const server = createServer((req, res) => {
    handle(cfg, req, res).catch((e) => {
      try {
        res.statusCode = 500;
        res.end(String((e as Error).message));
      } catch {
        /* response already sent */
      }
    });
  });
  server.listen(port, () => {
    banner(`⚒  Forge web UI`);
    info(`  open   http://localhost:${port}`);
    info(`  workspace: ${cfg.workspace}`);
    info(`  provider:  ${cfg.provider} · ${cfg.model}`);
    info(`  (Ctrl-C to stop)`);
  });
}

async function handle(
  cfg: ForgeConfig,
  req: IncomingMessage,
  res: ServerResponse,
): Promise<void> {
  const url = new URL(req.url ?? "/", "http://localhost");
  const path = url.pathname;

  if (path === "/" || path === "/index.html") {
    res.setHeader("content-type", "text/html; charset=utf-8");
    res.end(PAGE);
    return;
  }
  if (path === "/api/config") {
    return json(res, {
      provider: cfg.provider,
      model: cfg.model,
      workspace: cfg.workspace,
      permissionMode: cfg.permissionMode,
    });
  }
  if (path === "/api/tree") {
    const files: string[] = [];
    await walk(cfg.workspace, cfg.workspace, files);
    return json(res, files.slice(0, 400));
  }
  if (path === "/api/file") {
    const rel = url.searchParams.get("path") ?? "";
    try {
      const perms = new PermissionChecker(cfg.workspace, "readonly");
      const abs = perms.resolvePath(rel);
      const body = await readFile(abs, "utf8");
      res.setHeader("content-type", "text/plain; charset=utf-8");
      res.end(body.length > 200_000 ? body.slice(0, 200_000) + "\n…[truncated]" : body);
    } catch (e) {
      res.statusCode = 404;
      res.end(`cannot read: ${(e as Error).message}`);
    }
    return;
  }
  if (path === "/api/run" && req.method === "POST") {
    return runStream(cfg, req, res, false);
  }
  if (path === "/api/team" && req.method === "POST") {
    return runStream(cfg, req, res, true);
  }

  res.statusCode = 404;
  res.end("not found");
}

async function runStream(
  cfg: ForgeConfig,
  req: IncomingMessage,
  res: ServerResponse,
  team: boolean,
): Promise<void> {
  const body = await readBody(req);
  const mode = (body.mode as PermissionMode) || "auto";
  const model = typeof body.model === "string" && body.model ? body.model : cfg.model;
  const text = String((team ? body.goal : body.task) ?? "").trim();

  res.writeHead(200, {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    connection: "keep-alive",
  });
  const send = (obj: unknown) => res.write(`data: ${JSON.stringify(obj)}\n\n`);

  if (!text) {
    send({ type: "error", message: "empty request" });
    send({ type: "done", stopped: "done" });
    res.end();
    return;
  }

  const runCfg: ForgeConfig = { ...cfg, model, permissionMode: mode };
  const perms = new PermissionChecker(runCfg.workspace, mode); // no confirmer → deny gated actions
  const ctx: ToolContext = {
    workspace: runCfg.workspace,
    perms,
    log: () => {},
  };

  try {
    if (team) {
      const events: TeamEvents = {
        ...agentSse(send),
        onPhase: (phase) => send({ type: "phase", phase }),
        onPlan: (plan) => send({ type: "plan", plan }),
        onTaskStart: (t, index, total) =>
          send({ type: "task_start", role: t.role, title: t.title, index, total }),
        onTaskDone: (t, summary) => send({ type: "task_done", title: t.title, summary }),
        onReview: (report, approved) => send({ type: "review", report, approved }),
      };
      const result = await new Orchestrator(runCfg, ctx, events).build(text);
      send({ type: "done", stopped: result.approved ? "approved" : "changes_needed" });
    } else {
      const agent = new Agent({
        provider: createProvider(runCfg, model),
        tools: BASE_TOOLS,
        system: INTERACTIVE_SYSTEM,
        ctx,
        maxSteps: runCfg.maxSteps,
        temperature: runCfg.temperature,
        events: agentSse(send),
      });
      const run = await agent.run([userText(text)]);
      send({ type: "done", stopped: run.stopped });
    }
  } catch (e) {
    send({ type: "error", message: (e as Error).message });
    send({ type: "done", stopped: "error" });
  }
  res.end();
}

function agentSse(send: (o: unknown) => void): AgentEvents {
  return {
    onAssistantText: (text) => send({ type: "assistant", text }),
    onToolStart: (name, input) => send({ type: "tool", name, detail: detailOf(name, input) }),
    onToolResult: (_name, result, isError) =>
      send({ type: "tool_result", preview: firstLine(result), isError }),
  };
}

function detailOf(name: string, input: Record<string, unknown>): string {
  if (name === "bash") return String(input.command ?? "");
  if (typeof input.path === "string") return input.path;
  if (typeof input.pattern === "string") return input.pattern;
  return "";
}

function firstLine(s: string): string {
  const l = (s.split("\n")[0] ?? "").trim();
  return l.length > 120 ? l.slice(0, 120) + "…" : l;
}

async function walk(dir: string, root: string, out: string[]): Promise<void> {
  if (out.length > 400) return;
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const e of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (SKIP.has(e.name) || e.name.startsWith(".")) continue;
    const full = join(dir, e.name);
    if (e.isDirectory()) await walk(full, root, out);
    else out.push(relative(root, full));
  }
}

function readBody(req: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolveP) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => {
      try {
        resolveP(data ? (JSON.parse(data) as Record<string, unknown>) : {});
      } catch {
        resolveP({});
      }
    });
  });
}

function json(res: ServerResponse, obj: unknown): void {
  res.setHeader("content-type", "application/json");
  res.end(JSON.stringify(obj));
}

#!/usr/bin/env node
import { loadConfig, type ForgeConfig, type PermissionMode } from "./config/config.js";
import { createProvider } from "./llm/factory.js";
import { userText } from "./llm/types.js";
import { PermissionChecker } from "./safety/permissions.js";
import { BASE_TOOLS } from "./tools/index.js";
import type { ToolContext } from "./tools/types.js";
import { Agent } from "./agent/agent.js";
import { INTERACTIVE_SYSTEM } from "./orchestrator/roles.js";
import { startRepl } from "./cli/repl.js";
import { runTeam } from "./cli/team.js";
import { startServer } from "./web/server.js";
import { makeAgentEvents } from "./cli/agentEvents.js";
import { banner, info, ok, err, warn, c, Spinner } from "./cli/render.js";

const VERSION = "0.1.0";

const USAGE = `⚒  Forge — a local, self-hosted agentic dev super-app

Usage:
  forge                      start the interactive REPL (default)
  forge chat                 same as above
  forge run "<task>"         run one task non-interactively and exit
  forge build "<goal>"       run the full agent team (PM → coders → tester → devops → review)
  forge serve [--port N]     start the local web UI (browser dashboard) on localhost
  forge doctor               check connectivity to the configured LLM provider
  forge config               print the resolved configuration
  forge help                 show this help

Options (build/run):
  --provider <ollama|openai|anthropic>
  --model <name>
  --mode <safe|auto|yolo|readonly>   (build/run default: auto)
  --workspace <dir>

Configuration is read from flags, then .env / environment, then
forge.config.json (workspace or ~/.forge), then defaults. See .env.example.`;

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const { positionals, flags } = parseArgs(argv);
  const command = positionals[0] ?? "chat";

  if (flags.version || command === "version" || command === "--version") {
    console.log(`forge ${VERSION}`);
    return;
  }
  if (command === "help" || flags.help) {
    console.log(USAGE);
    return;
  }

  const overrides: Partial<ForgeConfig> = {};
  if (typeof flags.provider === "string") overrides.provider = flags.provider as ForgeConfig["provider"];
  if (typeof flags.model === "string") overrides.model = flags.model;
  if (typeof flags["base-url"] === "string") overrides.baseUrl = flags["base-url"];
  if (typeof flags["ollama-host"] === "string") overrides.ollamaHost = flags["ollama-host"];
  if (typeof flags.workspace === "string") overrides.workspace = flags.workspace;
  if (typeof flags.mode === "string") overrides.permissionMode = flags.mode as PermissionMode;

  const cfg = loadConfig(overrides);

  switch (command) {
    case "chat":
      await startRepl(cfg);
      break;
    case "build": {
      const goal = positionals.slice(1).join(" ").trim();
      if (!goal) { err('Provide a goal: forge build "<goal>"'); process.exitCode = 1; return; }
      const teamCfg = { ...cfg, permissionMode: overrides.permissionMode ?? "auto" as PermissionMode };
      await runTeam(teamCfg, goal);
      break;
    }
    case "run": {
      const task = positionals.slice(1).join(" ").trim();
      if (!task) { err('Provide a task: forge run "<task>"'); process.exitCode = 1; return; }
      await runOnce({ ...cfg, permissionMode: overrides.permissionMode ?? "auto" as PermissionMode }, task);
      break;
    }
    case "serve": {
      const port = typeof flags.port === "string" ? Number.parseInt(flags.port, 10) : 7878;
      startServer(cfg, Number.isFinite(port) ? port : 7878);
      break;
    }
    case "doctor":
      await doctor(cfg);
      break;
    case "config":
      printConfig(cfg);
      break;
    default:
      err(`Unknown command: ${command}`);
      console.log(USAGE);
      process.exitCode = 1;
  }
}

async function runOnce(cfg: ForgeConfig, task: string): Promise<void> {
  const perms = new PermissionChecker(cfg.workspace, cfg.permissionMode);
  const ctx: ToolContext = { workspace: cfg.workspace, perms, log: (l) => info("  " + l) };
  const spinner = new Spinner();
  const agent = new Agent({
    provider: createProvider(cfg),
    tools: BASE_TOOLS,
    system: INTERACTIVE_SYSTEM,
    ctx,
    maxSteps: cfg.maxSteps,
    temperature: cfg.temperature,
    events: makeAgentEvents(spinner),
  });
  banner("⚒  Forge");
  info(`task: ${task}\n`);
  try {
    const run = await agent.run([userText(task)]);
    spinner.stop();
    if (run.stopped === "max_steps") warn(`(stopped after ${run.steps} steps)`);
    else if (run.stopped === "stuck") warn(`(stopped: model repeated failing tool calls)`);
  } catch (e) {
    spinner.stop();
    err(`error: ${(e as Error).message}`);
    process.exitCode = 1;
  }
}

async function doctor(cfg: ForgeConfig): Promise<void> {
  banner("⚒  Forge doctor");
  printConfig(cfg);
  const spinner = new Spinner();
  spinner.start("contacting provider…");
  try {
    const provider = createProvider(cfg);
    const res = await provider.complete({
      messages: [userText("Reply with exactly: ok")],
      maxTokens: 16,
    });
    spinner.stop();
    ok(`✓ ${cfg.provider}/${cfg.model} responded: ${res.text.trim().slice(0, 60) || "(empty)"}`);
  } catch (e) {
    spinner.stop();
    err(`✗ provider check failed: ${(e as Error).message}`);
    info("\nHints:");
    info("  • ollama:    is `ollama serve` running and the model pulled?");
    info("  • openai:    is FORGE_BASE_URL pointing at your server's /v1 root?");
    info("  • anthropic: is ANTHROPIC_API_KEY set?");
    process.exitCode = 1;
  }
}

function printConfig(cfg: ForgeConfig): void {
  const masked = (s?: string) => (s ? s.slice(0, 4) + "…" : "(unset)");
  console.log(c.bold("\nResolved configuration:"));
  console.log(`  provider        ${cfg.provider}`);
  console.log(`  model           ${cfg.model}`);
  console.log(`  workspace       ${cfg.workspace}`);
  console.log(`  permissionMode  ${cfg.permissionMode}`);
  console.log(`  maxSteps        ${cfg.maxSteps}`);
  console.log(`  maxTokens       ${cfg.maxTokens}`);
  console.log(`  temperature     ${cfg.temperature}`);
  console.log(`  baseUrl         ${cfg.baseUrl}`);
  console.log(`  ollamaHost      ${cfg.ollamaHost}`);
  console.log(`  openaiApiKey    ${masked(cfg.openaiApiKey)}`);
  console.log(`  anthropicApiKey ${masked(cfg.anthropicApiKey)}\n`);
}

interface ParsedArgs {
  positionals: string[];
  flags: Record<string, string | boolean>;
}

function parseArgs(argv: string[]): ParsedArgs {
  const positionals: string[] = [];
  const flags: Record<string, string | boolean> = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next && !next.startsWith("--")) {
        flags[key] = next;
        i++;
      } else {
        flags[key] = true;
      }
    } else {
      positionals.push(a);
    }
  }
  return { positionals, flags };
}

main().catch((e) => {
  err(`fatal: ${(e as Error).stack ?? (e as Error).message}`);
  process.exitCode = 1;
});

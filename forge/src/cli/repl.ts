import * as readline from "node:readline/promises";
import { stdin, stdout } from "node:process";
import type { ForgeConfig, PermissionMode } from "../config/config.js";
import { createProvider } from "../llm/factory.js";
import type { Message } from "../llm/types.js";
import { userText } from "../llm/types.js";
import { PermissionChecker } from "../safety/permissions.js";
import { BASE_TOOLS } from "../tools/index.js";
import type { ToolContext } from "../tools/types.js";
import { Agent } from "../agent/agent.js";
import { INTERACTIVE_SYSTEM } from "../orchestrator/roles.js";
import { makeAgentEvents } from "./agentEvents.js";
import { banner, info, warn, err, ok, c, Spinner } from "./render.js";
import { runTeam } from "./team.js";

const HELP = `
Commands:
  /help              show this help
  /team <goal>       run the full agent team (PM → coders → tester → devops → review)
  /tools             list available tools
  /provider          show the active provider/model
  /model <name>      switch model for this session
  /mode <mode>       set permission mode: safe | auto | yolo | readonly
  /clear             clear the conversation history
  /exit, /quit       leave Forge

Anything else is sent to the agent as a task. The agent can read/write files,
run shell commands, and search the codebase within the workspace sandbox.`;

export async function startRepl(cfg: ForgeConfig): Promise<void> {
  const rl = readline.createInterface({ input: stdin, output: stdout });
  let mode: PermissionMode = cfg.permissionMode;
  let model = cfg.model;
  const spinner = new Spinner();

  const confirmer = async (prompt: string): Promise<boolean> => {
    spinner.stop();
    const ans = await rl.question(c.yellow(`\n${prompt}\n  approve? [y/N] `));
    return /^y(es)?$/i.test(ans.trim());
  };

  banner("⚒  Forge — local autonomous dev super-app");
  info(`workspace: ${cfg.workspace}`);
  info(`provider:  ${cfg.provider} · model: ${model} · mode: ${mode}`);
  info("type /help for commands, /exit to quit\n");

  let history: Message[] = [];

  for (;;) {
    let line: string;
    try {
      line = (await rl.question(c.cyan("forge › "))).trim();
    } catch {
      break; // ctrl-d / closed
    }
    if (!line) continue;

    if (line.startsWith("/")) {
      const [cmd, ...rest] = line.slice(1).split(" ");
      const arg = rest.join(" ").trim();
      if (cmd === "exit" || cmd === "quit") break;
      if (cmd === "help") { console.log(HELP); continue; }
      if (cmd === "clear") { history = []; ok("history cleared"); continue; }
      if (cmd === "tools") {
        for (const t of BASE_TOOLS) console.log(`  ${c.bold(t.name)} — ${t.description.split(".")[0]}`);
        continue;
      }
      if (cmd === "provider") { info(`${cfg.provider} · ${model} · mode ${mode}`); continue; }
      if (cmd === "model") {
        if (!arg) { warn("usage: /model <name>"); continue; }
        model = arg; ok(`model → ${model}`); continue;
      }
      if (cmd === "mode") {
        if (!["safe", "auto", "yolo", "readonly"].includes(arg)) {
          warn("usage: /mode safe|auto|yolo|readonly"); continue;
        }
        mode = arg as PermissionMode; ok(`permission mode → ${mode}`); continue;
      }
      if (cmd === "team") {
        if (!arg) { warn("usage: /team <goal>"); continue; }
        const teamCfg = { ...cfg, model, permissionMode: mode === "safe" ? "auto" : mode };
        await runTeam(teamCfg, arg, confirmer);
        continue;
      }
      warn(`unknown command: /${cmd} (try /help)`);
      continue;
    }

    // Treat as a task for the interactive agent.
    const perms = new PermissionChecker(cfg.workspace, mode, confirmer);
    const ctx: ToolContext = {
      workspace: cfg.workspace,
      perms,
      log: (l) => info("  " + l),
    };
    const provider = createProvider(cfg, model);
    const agent = new Agent({
      provider,
      tools: BASE_TOOLS,
      system: INTERACTIVE_SYSTEM,
      ctx,
      maxSteps: cfg.maxSteps,
      temperature: cfg.temperature,
      events: makeAgentEvents(spinner),
    });

    history.push(userText(line));
    try {
      const run = await agent.run(history);
      history = run.messages;
      if (run.stopped === "max_steps") warn(`(stopped after ${run.steps} steps)`);
      else if (run.stopped === "stuck")
        warn(`(stopped: the model repeated failing tool calls — try /mode or a different model)`);
    } catch (e) {
      spinner.stop();
      err(`error: ${(e as Error).message}`);
    }
  }

  rl.close();
  info("bye.");
}

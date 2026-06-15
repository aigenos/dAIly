# ⚒ Forge — a local, self-hosted agentic dev super-app

> A Claude Code / Cowork–style terminal agent **plus an autonomous engineering
> team** (PM → Architect → Coders → Tester → DevOps → Reviewer), pointed at
> **your own LLM** and sandboxed to your project. No accounts, no installs of
> other tools — just Node and the LLM endpoint you already run.

Forge gives you two modes from one binary:

1. **Interactive agent** (`forge`) — a terminal coding assistant that reads,
   writes, and edits files, runs shell commands, and searches your codebase,
   one task at a time, with a permission sandbox. This is the "Claude Code"
   experience against your local model.
2. **Autonomous team** (`forge build "<goal>"` or `/team` in the REPL) — a PM
   decomposes your goal into a plan, then role-specialized agents (architect,
   coders, tester, devops) execute it task by task, and a reviewer verifies the
   result and triggers a remediation round if needed. This is the "Cowork +
   autonomous agents" experience.

Everything runs locally and talks to **whichever LLM backend you choose**.

---

## Why this exists

You wanted something as capable as Claude Code / Cowork, with a full agent team,
that you can run **in a safer local environment against your own LLM services**
without the hassle of installing and wiring up those products. Forge is exactly
that: a single dependency-light Node CLI, three pluggable backends, a hard
filesystem sandbox, and a real multi-agent orchestrator.

## LLM backends (bring your own)

Pick per the `FORGE_PROVIDER` env var or `--provider` flag — no code changes:

| Provider | Endpoint | Use it for | Auth |
|----------|----------|-----------|------|
| `ollama` (default) | `OLLAMA_HOST` `/api/chat` | Fully local, easiest setup | none |
| `openai` | `FORGE_BASE_URL` `/chat/completions` | **Any OpenAI-compatible server**: vLLM, LM Studio, LocalAI, llama.cpp, OpenRouter, Together, Groq… | optional `OPENAI_API_KEY` |
| `anthropic` | `api.anthropic.com/v1/messages` | Optional frontier-quality cloud fallback | `ANTHROPIC_API_KEY` |

Default models per provider: `qwen2.5-coder:7b` (ollama), `gpt-oss` (openai),
`claude-opus-4-8` (anthropic). Override with `--model` / `FORGE_MODEL`.

> Tool calling needs a model that supports it. For local use, coder-tuned
> tool-calling models (e.g. `qwen2.5-coder`, `llama3.1`, `gpt-oss`) work well.

## Install & build

```bash
cd forge
npm install
npm run build          # compiles to dist/
npm link               # optional: puts `forge` on your PATH
```

Or run without linking:

```bash
node dist/index.js <command>      # built
npm run dev -- <command>          # from TypeScript source via tsx
```

## Quick start

```bash
# 0. one-time: configure your backend
cp .env.example .env              # edit FORGE_PROVIDER / model / endpoint

# 1. fully local with Ollama
ollama serve & ollama pull qwen2.5-coder:7b
forge doctor                      # verify connectivity

# 2. interactive agent (Claude Code style)
forge                             # opens the REPL in the current directory

# 3. autonomous team on a goal
forge build "add a /health endpoint to the Express app and a test for it"
```

### Point it at an OpenAI-compatible server

```bash
forge --provider openai --base-url http://localhost:8000/v1 --model my-model doctor
# (vLLM/LM Studio/etc. — anything that speaks /v1/chat/completions)
```

## Commands

```
forge                      interactive REPL (default)
forge run "<task>"         run one task non-interactively and exit
forge build "<goal>"       run the full agent team
forge serve [--port N]     local web UI dashboard (default port 7878)
forge doctor               check the configured LLM endpoint
forge config               print the resolved configuration
forge help                 usage

Flags (build/run): --provider --model --base-url --ollama-host --mode --workspace
```

### REPL slash commands

```
/team <goal>     run the agent team from inside the chat
/tools           list available tools
/model <name>    switch model for the session
/mode <mode>     safe | auto | yolo | readonly
/provider        show active provider/model
/clear           reset conversation
/help  /exit
```

## Web UI

Prefer a browser to the terminal? `forge serve` starts a local dashboard:

```bash
forge serve                       # → http://localhost:7878
forge serve --port 8080 --provider ollama --model qwen2.5-coder:7b
```

It's a single self-contained page (no bundler, no CDN, no runtime deps — served
straight from the same Node process) with:

- a chat box that runs either a **single task** or the **full agent team**,
- a **live event stream** (assistant text, every tool call + result, plan,
  per-task progress, and the reviewer verdict) pushed over Server-Sent Events,
- a **workspace file tree** that refreshes as the agents write files, with a
  click-to-view file viewer (also sandboxed to the workspace),
- a permission-mode selector (auto / yolo / readonly).

Same engine as the CLI — the browser is just another front-end over the agent
loop and orchestrator.

## Safety model

Forge is built to run locally and safely:

- **Filesystem sandbox** — every file path is resolved and confined to the
  workspace root. Path traversal (`../`, absolute paths outside the root) is
  rejected before any read/write.
- **Command policy** — dangerous shell patterns (recursive root deletes, `mkfs`,
  device writes, fork bombs, pipe-to-shell, force-push…) are blocked outright
  except in `yolo` mode.
- **Permission modes:**
  - `safe` (REPL default) — read-only commands auto-run; mutating commands and
    shell writes prompt you for approval.
  - `auto` (team default) — run anything not flagged dangerous, no prompts.
  - `yolo` — run everything, including flagged commands (asks once).
  - `readonly` — never modifies the filesystem; read/search only.

## How the agent team works

```
goal ─► PM (plan as JSON: overview + architecture + ordered tasks)
          │
          ▼   per task, a role-specialized agent runs the full tool loop
        architect ─► coder ─► … ─► tester ─► devops      (shared workspace + context)
          │
          ▼
        reviewer ─► reads changed files, runs build/tests, votes APPROVED / CHANGES_NEEDED
          │            └─ if changes needed: one remediation (coder) round, then re-review
          ▼
        result (plan, per-task summaries, review verdict)
```

Each agent shares the same sandboxed workspace and an accumulating context of
prior task summaries, so later agents build on earlier work.

## Architecture

```
src/
  llm/            provider abstraction + adapters (anthropic, openai, ollama) + http retry
  tools/          read/write/edit files, list, search_text, glob, bash, task_complete
  safety/         path sandbox + shell command policy + permission modes
  agent/          the tool-using agent loop (provider-agnostic)
  orchestrator/   PM planner, role system prompts, multi-agent orchestrator
  cli/            REPL, team runner, terminal rendering, arg parsing
  config/         env / .env / forge.config.json / flag resolution
```

Runtime dependencies: **none** (uses Node 20+ built-in `fetch`, `readline`,
`fs`). Dev-only: TypeScript, tsx, vitest.

## Configuration precedence

flags → `.env` / environment → `forge.config.json` (workspace or `~/.forge`) →
defaults. See [`.env.example`](.env.example) for every knob.

## Tests

```bash
npm test            # vitest: providers, planner, sandbox, command policy
npm run typecheck
```

## Roadmap / extension points

- Token streaming for live output (adapters currently complete-then-render).
- Per-role model selection (e.g. a small fast model for the reviewer).
- MCP tool integration and a memory store for cross-session context.
- Web UI: in-browser diff view and human-in-the-loop approvals over the wire.

## License

MIT

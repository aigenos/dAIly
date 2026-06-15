import type { Provider, Message, ToolUseBlock, ToolResultBlock } from "../llm/types.js";
import { toolResults as toolResultsMsg, userText } from "../llm/types.js";
import { TASK_COMPLETE } from "../tools/finish.js";
import { toSchemas, toolRegistry, type Tool } from "../tools/index.js";
import type { ToolContext } from "../tools/types.js";

export interface AgentEvents {
  onAssistantText?: (text: string) => void;
  onToolStart?: (name: string, input: Record<string, unknown>) => void;
  onToolResult?: (name: string, result: string, isError: boolean) => void;
  onStep?: (step: number, max: number) => void;
}

export interface AgentOptions {
  provider: Provider;
  tools: Tool[];
  system: string;
  ctx: ToolContext;
  maxSteps: number;
  temperature?: number;
  maxTokens?: number;
  events?: AgentEvents;
  /** Abort after this many consecutive steps where every tool call errored. */
  maxDeadSteps?: number;
}

export interface AgentRun {
  /** Final assistant text (last turn with no tool calls). */
  text: string;
  /** Summary supplied via task_complete, if the agent declared completion. */
  completion?: string;
  /** Full message history including this run, for continuation. */
  messages: Message[];
  steps: number;
  stopped: "done" | "completed" | "max_steps" | "stuck";
}

/**
 * A tool-using agent loop. Provider-agnostic: it asks the LLM for the next
 * action, executes any tool calls against the sandbox, feeds results back, and
 * repeats until the model stops calling tools (or declares completion).
 */
export class Agent {
  private readonly registry: Map<string, Tool>;

  constructor(private readonly opts: AgentOptions) {
    this.registry = toolRegistry(opts.tools);
  }

  /** Run starting from an existing message history. */
  async run(history: Message[]): Promise<AgentRun> {
    const messages = [...history];
    const schemas = toSchemas(this.opts.tools);
    const { provider, ctx, maxSteps, events } = this.opts;
    const maxDeadSteps = this.opts.maxDeadSteps ?? 6;
    let deadSteps = 0;

    for (let step = 1; step <= maxSteps; step++) {
      events?.onStep?.(step, maxSteps);

      const result = await provider.complete({
        system: this.opts.system,
        messages,
        tools: schemas,
        temperature: this.opts.temperature,
        maxTokens: this.opts.maxTokens,
      });

      // Record the assistant turn (text + any tool calls).
      const assistantContent = [];
      if (result.text) assistantContent.push({ type: "text" as const, text: result.text });
      for (const tc of result.toolCalls) assistantContent.push(tc);
      messages.push({ role: "assistant", content: assistantContent });
      if (result.text) events?.onAssistantText?.(result.text);

      if (result.toolCalls.length === 0) {
        return { text: result.text, messages, steps: step, stopped: "done" };
      }

      const results: ToolResultBlock[] = [];
      let completion: string | undefined;
      let anyOk = false;
      for (const tc of result.toolCalls) {
        const { content, isError } = await this.execTool(tc, ctx);
        results.push({ type: "tool_result", toolUseId: tc.id, content, isError });
        events?.onToolResult?.(tc.name, content, !!isError);
        if (!isError) anyOk = true;
        if (tc.name === TASK_COMPLETE && !isError) completion = content;
      }
      messages.push(toolResultsMsg(results));

      if (completion !== undefined) {
        return { text: result.text, completion, messages, steps: step, stopped: "completed" };
      }

      // Bail out if the model is stuck repeating failing tool calls with no
      // successful action — avoids burning every step on a confused model.
      deadSteps = anyOk ? 0 : deadSteps + 1;
      if (deadSteps >= maxDeadSteps) {
        return { text: result.text, messages, steps: step, stopped: "stuck" };
      }
    }

    return {
      text: "",
      messages,
      steps: maxSteps,
      stopped: "max_steps",
    };
  }

  /** Convenience: run a single user task from scratch. */
  async runTask(task: string): Promise<AgentRun> {
    return this.run([userText(task)]);
  }

  private async execTool(
    tc: ToolUseBlock,
    ctx: ToolContext,
  ): Promise<{ content: string; isError?: boolean }> {
    const tool = this.registry.get(tc.name);
    if (!tool) {
      return { content: `Unknown tool: ${tc.name}`, isError: true };
    }
    if (tool.mutating && !ctx.perms.canMutate()) {
      return {
        content: `Tool ${tc.name} is disabled in readonly permission mode.`,
        isError: true,
      };
    }
    this.opts.events?.onToolStart?.(tc.name, tc.input);
    try {
      const content = await tool.run(tc.input, ctx);
      return { content };
    } catch (err) {
      return { content: `Error: ${(err as Error).message}`, isError: true };
    }
  }
}

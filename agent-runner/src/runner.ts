declare const process: {
  stdin: AsyncIterable<Uint8Array>;
  stdout: { write(chunk: string): void };
  stderr: { write(chunk: string): void };
  exitCode?: number;
};

type AgentBackendId = "opencode" | "codex" | "anthropic";
type AgentAction = "analyze" | "rebase" | "fix_conflicts" | "address_review" | "fix_checks";
type RunStatus = "running" | "patch_ready" | "awaiting_approval" | "failed";

type RunnerInput = {
  backendId: AgentBackendId;
  repository: string;
  pullRequestId: string;
  pullRequestNumber: number;
  action: AgentAction;
  repositoryLocalPath: string;
  baseBranch?: string | null;
  sourceBranch?: string | null;
  runnerTimeoutSeconds?: number;
  conflictFiles?: string[];
};

type RunnerEvent =
  | { type: "log"; message: string; createdAt?: string }
  | { type: "final"; status: RunStatus; summary: string; backendSessionId?: string; output?: string; createdAt?: string };

const dynamicImport = new Function("specifier", "return import(specifier)") as <T = unknown>(specifier: string) => Promise<T>;

async function main() {
  const input = parseInput(await readStdin());
  emit({ type: "log", message: `Starting ${input.backendId} run for ${input.repository}#${input.pullRequestNumber}` });

  switch (input.backendId) {
    case "opencode":
      await runOpenCode(input);
      return;
    case "codex":
      await runCodex(input);
      return;
    case "anthropic":
      await runAnthropic(input);
      return;
  }
}

async function runOpenCode(input: RunnerInput) {
  let server: { close(): void } | undefined;
  try {
    emit({ type: "log", message: "Loading OpenCode SDK" });
    const { createOpencode } = await dynamicImport<{
      createOpencode(options?: { timeout?: number; port?: number; config?: unknown }): Promise<{ client: any; server: { url: string; close(): void } }>;
    }>("@opencode-ai/sdk");
    const instance = await createOpencode({
      timeout: 120_000,
      port: 0,
      // The MergeOps worker owns the deadline; OpenCode's provider default is 5 minutes.
      config: { provider: { deepseek: { options: { timeout: false } } } }
    });
    server = instance.server;
    emit({ type: "log", message: "OpenCode session server started" });
    const session = await unwrapData<unknown>(instance.client.session.create({
      query: { directory: input.repositoryLocalPath }
    }));
    const sessionId = readSessionId(session);
    emit({ type: "log", message: `OpenCode session created: ${sessionId}` });
    await unwrapData<unknown>(instance.client.session.promptAsync({
      path: { id: sessionId },
      query: { directory: input.repositoryLocalPath },
      body: { parts: [{ type: "text", text: buildPrompt(input) }] }
    }));
    emit({ type: "log", message: "Prompt submitted; polling agent status" });
    await waitForOpenCodeIdle(instance.client.session, sessionId, input.repositoryLocalPath);
    const messages = await unwrapData<unknown>(instance.client.session.messages({
      path: { id: sessionId },
      query: { directory: input.repositoryLocalPath }
    }));
    const agentError = readAgentError(messages);
    if (agentError) {
      throw new Error(`OpenCode agent error: ${agentError}`);
    }
    emit({ type: "log", message: `OpenCode returned ${readMessageCount(messages)} session message(s)` });
    emit({ type: "log", message: "OpenCode agent completed" });
    emitFinal(
      "awaiting_approval",
      `OpenCode completed for ${input.repository}#${input.pullRequestNumber}. Review the local diff before approval.`,
      sessionId,
      readAgentOutput(messages)
    );
  } catch (error) {
    emitFinal("failed", runnerFailureSummary("OpenCode", error));
  } finally {
    server?.close();
  }
}

async function waitForOpenCodeIdle(sessionClient: any, sessionId: string, directory: string) {
  let lastStatus = "";
  for (;;) {
    const statuses = await unwrapData<unknown>(sessionClient.status({ query: { directory } }));
    const status = statuses && typeof statuses === "object" ? (statuses as Record<string, { type?: unknown }>)[sessionId] : undefined;
    if (status?.type === "idle") return;
    if (status?.type === "retry" && lastStatus !== "retry") {
      emit({ type: "log", message: `OpenCode provider retry: ${typeof (status as { message?: unknown }).message === "string" ? (status as { message: string }).message : "retrying"}` });
    } else if (status?.type === "busy" && lastStatus !== "busy") {
      emit({ type: "log", message: "OpenCode agent is working" });
    }
    lastStatus = typeof status?.type === "string" ? status.type : "unknown";
    await sleep(5000);
  }
}

function sleep(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

function readSessionId(value: unknown): string {
  if (value && typeof value === "object") {
    const candidate = value as { id?: unknown; data?: { id?: unknown }; info?: { id?: unknown } };
    if (typeof candidate.id === "string" && candidate.id) return candidate.id;
    if (typeof candidate.data?.id === "string" && candidate.data.id) return candidate.data.id;
    if (typeof candidate.info?.id === "string" && candidate.info.id) return candidate.info.id;
  }
  throw new Error(`OpenCode returned an invalid session response: ${JSON.stringify(value)}`);
}

function readAgentError(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as { error?: unknown; info?: { error?: unknown }; data?: unknown };
  const errors = [candidate.error, candidate.info?.error];
  if (Array.isArray(candidate.data)) {
    errors.push(...candidate.data.map((item) => item && typeof item === "object" ? (item as { error?: unknown }).error : undefined));
  }
  for (const error of errors) {
    if (typeof error === "string" && error) return error;
    if (error && typeof error === "object") {
      const details = error as { message?: unknown; name?: unknown };
      if (typeof details.message === "string" && details.message) return details.message;
      if (typeof details.name === "string" && details.name) return details.name;
    }
  }
  return null;
}

function readMessageCount(value: unknown): number {
  if (!Array.isArray(value)) return 0;
  return value.length;
}

function readAgentOutput(value: unknown): string | undefined {
  if (!Array.isArray(value)) return undefined;
  const output = value.flatMap((message) => {
    if (!message || typeof message !== "object") return [];
    const record = message as { info?: { role?: unknown }; parts?: unknown };
    if (record.info?.role !== "assistant" || !Array.isArray(record.parts)) return [];
    return record.parts.flatMap((part) => {
      if (!part || typeof part !== "object") return [];
      const text = (part as { type?: unknown; text?: unknown });
      return text.type === "text" && typeof text.text === "string" ? [text.text] : [];
    });
  }).join("\n\n").trim();
  return output ? output.slice(-20000) : undefined;
}

async function runCodex(input: RunnerInput) {
  try {
    emit({ type: "log", message: "Loading Codex SDK" });
    const { Codex } = await dynamicImport<{ Codex: new () => { startThread(): { run(prompt: string): Promise<{ finalResponse?: string }> } } }>("@openai/codex-sdk");
    const codex = new Codex();
    const thread = codex.startThread();
    emit({ type: "log", message: "Codex thread started" });
    const result = await thread.run(buildPrompt(input));
    emit({ type: "log", message: "Codex thread completed" });
    emitFinal("awaiting_approval", result.finalResponse ?? "Codex completed. Review the local diff before approval.");
  } catch (error) {
    emitFinal("failed", missingDependencySummary("Codex", error));
  }
}

async function runAnthropic(input: RunnerInput) {
  try {
    emit({ type: "log", message: "Loading Claude SDK" });
    const { query } = await dynamicImport<{ query(params: { prompt: string; options: { cwd: string; permissionMode: string } }): AsyncIterable<unknown> }>("@anthropic-ai/claude-agent-sdk");
    let finalSummary = "Claude run completed. Review the local diff before approval.";
    for await (const message of query({ prompt: buildPrompt(input), options: { cwd: input.repositoryLocalPath, permissionMode: "default" } })) {
      const maybeResult = message as { type?: string; subtype?: string; result?: string };
      if (maybeResult.type) emit({ type: "log", message: `Claude event: ${maybeResult.type}${maybeResult.subtype ? `/${maybeResult.subtype}` : ""}` });
      if (maybeResult.type === "result" && maybeResult.subtype === "success" && typeof maybeResult.result === "string") {
        finalSummary = maybeResult.result;
      }
    }
    emitFinal("awaiting_approval", finalSummary);
  } catch (error) {
    emitFinal("failed", missingDependencySummary("Claude", error));
  }
}

function buildPrompt(input: RunnerInput) {
  const completionRules = input.action === "fix_conflicts" || input.action === "rebase"
    ? "Do not manually create commits. It is required to stage resolved conflict files and run git rebase --continue; that command creates the rebased commit. Do not push, merge, or open a pull request. Leave the workspace for human approval."
    : "Do not stage, commit, push, merge, or open a pull request. Leave the workspace for human approval.";
  const scope = input.action === "fix_conflicts"
    ? `Act immediately with shell commands; do not inspect the repository broadly. The only conflict files are: ${(input.conflictFiles ?? []).join(", ") || "the files reported by git"}. Resolve only those files, remove every conflict marker, stage those files, and run GIT_EDITOR=true git rebase --continue. Repeat status, resolve, stage, and rebase --continue until the rebase completes. NEVER run git merge or start a second rebase. Verify git diff --name-only --diff-filter=U is empty, run the relevant checks, and stop immediately. Do not touch any unrelated file.`
    : input.action === "rebase"
      ? "MergeOps has already started git rebase onto the base branch. If the rebase is paused on conflicts, resolve only those conflicts and run git rebase --continue until it completes. NEVER run git merge or start a second rebase. Keep the change narrowly scoped to the rebase and checks, then stop."
      : "Keep the change narrowly scoped to the requested task and stop after the smallest patch and checks are complete.";
  return [
    `Prepare ${input.action.replaceAll("_", " ")} for PR #${input.pullRequestNumber} in ${input.repository}.`,
    `Repository path: ${input.repositoryLocalPath}.`,
    input.sourceBranch ? `Source branch: ${input.sourceBranch}.` : "",
    input.baseBranch ? `Base branch: ${input.baseBranch}.` : "",
    "Inspect the repo and prepare the smallest patch and checks summary.",
    scope,
    completionRules
  ].filter(Boolean).join(" ");
}

function missingDependencySummary(name: string, error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return `${name} runner is not ready: ${message}. Run npm install and npm run build in agent-runner/.`;
}

function runnerFailureSummary(name: string, error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("Cannot find package") || message.includes("Cannot find module")) {
    return missingDependencySummary(name, error);
  }
  return `${name} runner failed: ${message}`;
}

async function unwrapData<T>(result: Promise<{ data?: T; error?: unknown }> | { data?: T; error?: unknown }): Promise<T> {
  const resolved = await result;
  if (resolved.error) {
    throw new Error(JSON.stringify(resolved.error));
  }
  if (resolved.data === undefined) {
    throw new Error("SDK returned no data");
  }
  return resolved.data;
}

async function readStdin() {
  const chunks: Uint8Array[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const length = chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

function parseInput(raw: string): RunnerInput {
  const parsed = JSON.parse(raw) as Partial<RunnerInput>;
  if (!parsed.backendId || !parsed.repository || !parsed.pullRequestNumber || !parsed.action || !parsed.repositoryLocalPath) {
    throw new Error("Invalid runner input");
  }
  return parsed as RunnerInput;
}

function emit(event: RunnerEvent) {
  process.stdout.write(`${JSON.stringify({ ...event, createdAt: new Date().toISOString() })}\n`);
}

function emitFinal(status: RunStatus, summary: string, backendSessionId?: string, output?: string) {
  emit({ type: "final", status, summary, backendSessionId, output });
}

main().catch((error) => {
  const summary = error instanceof Error ? error.message : String(error);
  emitFinal("failed", summary);
  process.exitCode = 1;
});

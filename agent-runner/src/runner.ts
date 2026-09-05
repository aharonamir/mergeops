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
};

type RunnerEvent =
  | { type: "log"; message: string; createdAt?: string }
  | { type: "final"; status: RunStatus; summary: string; backendSessionId?: string; createdAt?: string };

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
      createOpencode(options?: { timeout?: number }): Promise<{ client: any; server: { url: string; close(): void } }>;
    }>("@opencode-ai/sdk/v2");
    const instance = await createOpencode({ timeout: 120_000 });
    server = instance.server;
    emit({ type: "log", message: "OpenCode session server started" });
    const session = await unwrapData<{ id: string }>(instance.client.v2.session.create({
      location: { directory: input.repositoryLocalPath }
    }));
    emit({ type: "log", message: `OpenCode session created: ${session.id}` });
    await instance.client.v2.session.prompt({
      sessionID: session.id,
      delivery: "queue",
      prompt: { text: buildPrompt(input) }
    });
    emit({ type: "log", message: "Prompt queued; waiting for agent completion" });
    await instance.client.v2.session.wait({ sessionID: session.id });
    emit({ type: "log", message: "OpenCode agent completed" });
    emitFinal(
      "awaiting_approval",
      `OpenCode completed for ${input.repository}#${input.pullRequestNumber}. Review the local diff before approval.`,
      session.id
    );
  } catch (error) {
    emitFinal("failed", runnerFailureSummary("OpenCode", error));
  } finally {
    server?.close();
  }
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
  return [
    `Prepare ${input.action.replaceAll("_", " ")} for PR #${input.pullRequestNumber} in ${input.repository}.`,
    `Repository path: ${input.repositoryLocalPath}.`,
    input.sourceBranch ? `Source branch: ${input.sourceBranch}.` : "",
    input.baseBranch ? `Base branch: ${input.baseBranch}.` : "",
    "Inspect the repo and prepare the smallest patch and checks summary.",
    "Do not push, merge, or open a pull request. Stop for human approval."
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

function emitFinal(status: RunStatus, summary: string, backendSessionId?: string) {
  emit({ type: "final", status, summary, backendSessionId });
}

main().catch((error) => {
  const summary = error instanceof Error ? error.message : String(error);
  emitFinal("failed", summary);
  process.exitCode = 1;
});

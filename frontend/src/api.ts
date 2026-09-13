import { fixtureData } from "./fixtures";
import type { ActionRecord, AgentRun, AgentSettings, AppData, CheckoutResult, GitHubSettings, GitHubSyncResult, PrAnnotations, ReplyDraft, RepositoryConfig, ReviewThreadSnapshot, TeamMember } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 3000);
    const response = await fetch(`${API_BASE}/api/health`, { signal: controller.signal });
    window.clearTimeout(timeout);
    return response.ok;
  } catch {
    return false;
  }
}

export async function loadAppData(): Promise<AppData> {
  try {
    const response = await fetch(`${API_BASE}/api/app-data`);
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    return await response.json();
  } catch {
    return fixtureData;
  }
}

export async function createAgentRun(input: {
  backendId: string;
  pullRequestId: string;
  action: AgentRun["action"];
  reviewThreadIds?: string[];
}): Promise<AgentRun> {
  try {
    const response = await fetch(`${API_BASE}/api/agent-runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input)
    });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    return await response.json();
  } catch {
    const pr = fixtureData.pullRequests.find((item) => item.id === input.pullRequestId);
    return {
      id: `local-${Date.now()}`,
      backendId: input.backendId,
      repository: pr?.repository ?? "unknown",
      pullRequestId: input.pullRequestId,
      pullRequestNumber: pr?.number ?? 0,
      action: input.action,
      status: "awaiting_approval",
      requester: "local user",
      summary: "Local fixture run queued. No push will happen without approval.",
      createdAt: new Date().toISOString()
    };
  }
}

export async function createCheckout(pullRequestId: string): Promise<CheckoutResult> {
  const response = await fetch(`${API_BASE}/api/checkouts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pullRequestId })
  });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function clearAction(actionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/actions/${actionId}`, { method: "DELETE" });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
}

export async function loadActionDetails(actionId: string): Promise<AgentRun | ActionRecord> {
  const response = await fetch(`${API_BASE}/api/actions/${actionId}/details`);
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function cancelAgentRun(runId: string): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/agent-runs/${runId}/cancel`, { method: "POST" });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return await response.json();
}

export async function selectRebaseDecision(runId: string, optionId: "drop_base_sync_merge" | "manual"): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/agent-runs/${runId}/rebase-decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ optionId }) });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function reviewPatch(runId: string, backendId: string): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/agent-runs/${runId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ backendId })
  });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function approveAgentRun(runId: string): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/agent-runs/${runId}/approve`, { method: "POST" });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function pushAgentRun(runId: string, target: "mergeops_branch" | "pr_branch" = "mergeops_branch"): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/agent-runs/${runId}/push`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target }) });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function reviseAgentRun(runId: string, input: { backendId: string; instruction: string; reason?: string }): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/agent-runs/${runId}/revise`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function retryAgentRun(runId: string): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/agent-runs/${runId}/retry`, { method: "POST" });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function inspectRecoveryAgentRun(runId: string): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/agent-runs/${runId}/inspect-recovery`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed: true }) });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function loadReviewThreads(pullRequestId: string): Promise<ReviewThreadSnapshot> {
  const response = await fetch(`${API_BASE}/api/pull-requests/${pullRequestId}/review-threads`);
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function postReviewReplies(runId: string, replies: ReplyDraft[]): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/agent-runs/${runId}/review-replies`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ replies }) });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export function subscribeToAgentEvents(onEvent: () => void): () => void {
  if (typeof EventSource === "undefined") return () => undefined;
  const source = new EventSource(`${API_BASE}/api/agent-runs/events`);
  source.addEventListener("agent-run", onEvent);
  return () => source.close();
}

export async function loadPrAnnotations(pullRequestId: string): Promise<PrAnnotations> {
  const response = await fetch(`${API_BASE}/api/pull-requests/${pullRequestId}/annotations`);
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return await response.json();
}

export async function updatePrTags(pullRequestId: string, tags: string[]): Promise<PrAnnotations> {
  const response = await fetch(`${API_BASE}/api/pull-requests/${pullRequestId}/annotations/tags`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tags }) });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function createPrNote(pullRequestId: string, text: string): Promise<PrAnnotations> {
  const response = await fetch(`${API_BASE}/api/pull-requests/${pullRequestId}/annotations/notes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function deletePrNote(pullRequestId: string, noteId: string): Promise<PrAnnotations> {
  const response = await fetch(`${API_BASE}/api/pull-requests/${pullRequestId}/annotations/notes/${noteId}`, { method: "DELETE" });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `API returned ${response.status}`);
  return await response.json();
}

export async function updateTeamMember(memberId: string, patch: Partial<TeamMember>): Promise<TeamMember> {
  const response = await fetch(`${API_BASE}/api/team-members/${memberId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch)
  });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return await response.json();
}

export async function createTeamMember(input: Omit<TeamMember, "id">): Promise<TeamMember> {
  const response = await fetch(`${API_BASE}/api/team-members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return await response.json();
}

export async function deleteTeamMember(memberId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/team-members/${memberId}`, { method: "DELETE" });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
}

export async function updateGitHubSettings(input: {
  username?: string | null;
  token?: string;
  repositories?: RepositoryConfig[];
}): Promise<GitHubSettings> {
  const response = await fetch(`${API_BASE}/api/settings/github`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accessMode: "contributor_token", ...input })
  });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return await response.json();
}

export async function updateAgentSettings(input: AgentSettings): Promise<AgentSettings> {
  const response = await fetch(`${API_BASE}/api/settings/agent`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return await response.json();
}

export async function syncGitHub(): Promise<GitHubSyncResult> {
  const response = await fetch(`${API_BASE}/api/sync/github`, { method: "POST" });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return await response.json();
}

import { fixtureData } from "./fixtures";
import type { AgentRun, AppData, CheckoutResult, GitHubSettings, GitHubSyncResult, RepositoryConfig, TeamMember } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

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

export async function syncGitHub(): Promise<GitHubSyncResult> {
  const response = await fetch(`${API_BASE}/api/sync/github`, { method: "POST" });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return await response.json();
}

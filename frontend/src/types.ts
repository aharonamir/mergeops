export type ThemePreference = "system" | "light" | "dark";
export type View = "cockpit" | "team" | "agents" | "settings";
export type QueueFilter = "all" | "blocked" | "review" | "ready" | "merged";

export type TeamMember = {
  id: string;
  displayName: string;
  githubUsername: string;
  gitAliases: string[];
  emails: string[];
  currentFocus: string;
  responsibilities: string;
  ownedRepos: string[];
  ownedPaths: string[];
  expertiseTags: string[];
  timezone: string;
  availability: "active" | "focus_mode" | "ooo" | "overloaded" | "inactive";
};

export type PullRequest = {
  id: string;
  repository: string;
  repositoryFullName?: string | null;
  number: number;
  title: string;
  author: string;
  ownerMemberId: string;
  sourceBranch: string;
  baseBranch: string;
  state: "open" | "merged" | "closed" | "draft";
  mergeable: "mergeable" | "conflicting" | "unknown";
  reviewState: "approved" | "changes_requested" | "review_required" | "commented";
  unresolvedCommentCount: number;
  requestedReviewers: string[];
  checkState: "passing" | "failing" | "pending" | "not_run";
  linkedIssueIds: string[];
  changedFilesCount: number;
  ageDays: number;
  summary: string;
  searchText: string;
};

export type RepositoryConfig = {
  id: string;
  owner: string;
  name: string;
  defaultBranch: string;
  enabled: boolean;
  localPath?: string | null;
  lastSyncedAt?: string | null;
  lastSyncStatus?: string | null;
};

export type GitHubSettings = {
  accessMode: "contributor_token" | "device_login" | "github_app";
  hasToken: boolean;
  username?: string | null;
  repositories: RepositoryConfig[];
  lastSyncedAt?: string | null;
};

export type AgentBackend = {
  id: "opencode" | "codex" | "anthropic";
  displayName: string;
  adapterType: string;
  endpoint: string;
  defaultModel: string;
  enabled: boolean;
};

export type AgentRun = {
  id: string;
  backendId: string;
  repository: string;
  pullRequestId: string;
  pullRequestNumber: number;
  action: "analyze" | "rebase" | "fix_conflicts" | "address_review" | "fix_checks";
  status: "queued" | "running" | "patch_ready" | "checks_running" | "awaiting_approval" | "approved" | "pushed" | "failed" | "cancelled";
  requester: string;
  summary: string;
  backendSessionId?: string | null;
  workspacePath?: string | null;
  baseCommit?: string | null;
  createdAt: string;
};

export type AppData = {
  teamMembers: TeamMember[];
  pullRequests: PullRequest[];
  agentBackends: AgentBackend[];
  agentRuns: AgentRun[];
  github?: GitHubSettings | null;
};

export type GitHubSyncResult = {
  syncedAt: string;
  repositoriesScanned: number;
  pullRequestsImported: number;
  errors: string[];
};

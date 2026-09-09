export type ThemePreference = "system" | "light" | "dark";
export type View = "cockpit" | "team" | "agents" | "activity" | "settings";
export type QueueFilter = "all" | "conflict" | "review" | "merged" | "closed";

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
  requiredChecks?: string[];
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

export type AgentSettings = {
  runnerTimeoutSeconds: number;
};

export type AgentRun = {
  id: string;
  backendId: string;
  repository: string;
  pullRequestId: string;
  pullRequestNumber: number;
  action: "analyze" | "rebase" | "fix_conflicts" | "address_review" | "fix_checks" | "review_patch";
  status: "queued" | "running" | "patch_ready" | "review_ready" | "checks_running" | "awaiting_decision" | "awaiting_approval" | "approved" | "pushed" | "failed" | "cancelled";
  requester: string;
  summary: string;
  parentRunId?: string | null;
  agentOutput?: string | null;
  backendSessionId?: string | null;
  workspacePath?: string | null;
  baseCommit?: string | null;
  events?: AgentRunEvent[];
  patchSummary?: string | null;
  diff?: string | null;
  checks?: CheckResult[];
  riskSummary?: string | null;
  approval?: ApprovalRecord | null;
  pushRef?: string | null;
  rebaseEvidence?: RebaseEvidence | null;
  createdAt: string;
};

export type AgentRunSummary = {
  id: string;
  backendId: string;
  repository: string;
  pullRequestId: string;
  pullRequestNumber: number;
  action: string;
  status: string;
  requester: string;
  summary: string;
  parentRunId?: string | null;
  workspacePath?: string | null;
  baseCommit?: string | null;
  createdAt: string;
  eventCount?: number;
  checkCount?: number;
  conflictCount?: number;
  resolvedConflictCount?: number;
  blockedCommandCount?: number;
  hasRebaseEvidence?: boolean;
};

export type AgentRunEvent = {
  sequence: number;
  type: string;
  message: string;
  createdAt: string;
};

export type CheckResult = {
  name: string;
  status: "passed" | "failed" | "skipped";
  summary: string;
  output: string;
  startedAt: string;
  finishedAt: string;
};

export type BoundedText = {
  text: string;
  truncated: boolean;
  originalLength: number;
};

export type ConflictEvidence = {
  id: string;
  commitSha?: string | null;
  commitSubject?: string | null;
  filePath: string;
  ours: BoundedText;
  theirs: BoundedText;
  result: BoundedText;
  classification: "ours" | "theirs" | "combined" | "manual" | "added" | "deleted" | "unknown";
  validationState: "passed" | "failed" | "unknown";
  agentExplanation?: string | null;
  createdAt: string;
};

export type RebaseStage = {
  sequence: number;
  type: string;
  message: string;
  createdAt: string;
  commitSha?: string | null;
};

export type RebaseEvidence = {
  baseRef?: string | null;
  initialHead?: string | null;
  finalHead?: string | null;
  state: "not_applicable" | "running" | "completed" | "failed" | "cancelled";
  stages: RebaseStage[];
  conflicts: ConflictEvidence[];
  blockedCommands: string[];
  validation: string[];
  plan?: RebasePlan | null;
  decision?: RebaseDecision | null;
  diff: BoundedText;
  transcript: BoundedText;
};

export type RebasePlan = { strategy: "standard" | "drop_base_sync_merge"; targetRef: string; upstreamRef?: string | null; command: string; mergeCommit?: string | null; summary: string };
export type RebaseDecisionOption = { id: "drop_base_sync_merge" | "manual"; label: string; description: string; recommended: boolean };
export type RebaseDecision = { question: string; options: RebaseDecisionOption[]; selectedOption?: "drop_base_sync_merge" | "manual" | null };

export type ApprovalRecord = {
  id: string;
  runId: string;
  decision: "approved" | "rejected";
  reviewer: string;
  baseCommit?: string | null;
  createdAt: string;
};

export type ActionRecord = {
  id: string;
  kind: "checkout" | "agent_run";
  repository: string;
  pullRequestId: string;
  pullRequestNumber: number;
  action: string;
  status: string;
  summary: string;
  parentRunId?: string | null;
  agentOutput?: string | null;
  workspacePath?: string | null;
  baseCommit?: string | null;
  events?: AgentRunEvent[];
  patchSummary?: string | null;
  diff?: string | null;
  checks?: CheckResult[];
  riskSummary?: string | null;
  approval?: ApprovalRecord | null;
  pushRef?: string | null;
  rebaseEvidence?: RebaseEvidence | null;
  eventCount?: number;
  checkCount?: number;
  conflictCount?: number;
  resolvedConflictCount?: number;
  blockedCommandCount?: number;
  hasRebaseEvidence?: boolean;
  createdAt: string;
};

export type ActivityEvent = {
  id: string;
  kind: string;
  message: string;
  actionId?: string | null;
  createdAt: string;
};

export type CheckoutResult = {
  pullRequestId: string;
  status: "ready" | "failed";
  workspacePath?: string | null;
  baseCommit?: string | null;
  summary: string;
  action: ActionRecord;
};

export type AppData = {
  teamMembers: TeamMember[];
  pullRequests: PullRequest[];
  agentBackends: AgentBackend[];
  agentSettings: AgentSettings;
  agentRuns: AgentRunSummary[];
  actions?: ActionRecord[];
  activity?: ActivityEvent[];
  github?: GitHubSettings | null;
};

export type GitHubSyncResult = {
  syncedAt: string;
  repositoriesScanned: number;
  pullRequestsImported: number;
  errors: string[];
};

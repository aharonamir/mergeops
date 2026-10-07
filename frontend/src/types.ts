export type ThemePreference = "system" | "light" | "dark";
export type View = "cockpit" | "search" | "team" | "agents" | "activity" | "settings";
export type QueueFilter = "all" | "open" | "conflict" | "review" | "ready" | "needs_you" | "merged" | "closed";

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
  headRepositoryFullName?: string | null;
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

export type SearchSettings = { backend: "github" | "gitcode"; gitcodeRepositories: string[]; githubReady: boolean; gitcodeReady: boolean };
export type SearchResult = {
  source: "github" | "gitcode";
  kind: "pull_request" | "issue";
  repository: string;
  number: number;
  url: string;
  originalTitle: string;
  author: string;
  state: string;
  match: "confirmed" | "semantic";
  summary: { en: string; zh: string };
  reason: { en: string; zh: string };
  linkedItems: Array<{ kind: "pull_request" | "issue"; number: number; url: string }>;
};
export type SearchRun = {
  id: string;
  backendId: AgentBackend["id"];
  searchBackend: "github" | "gitcode";
  query: string;
  kind: "pull_requests" | "issues";
  repositoryIds: string[];
  memberId?: string | null;
  locale: "en" | "zh";
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | "formatting_error" | "interrupted";
  summary: string;
  results: SearchResult[];
  rawOutput?: string | null;
  errors: string[];
  events: Array<{ type: string; message: string; createdAt: string }>;
  workspacePath?: string | null;
  createdAt: string;
  completedAt?: string | null;
};

export type AgentRun = {
  id: string;
  backendId: string;
  repository: string;
  pullRequestId: string;
  pullRequestNumber: number;
  action: "analyze" | "review_pr" | "rebase" | "fix_conflicts" | "address_review" | "fix_checks" | "review_patch" | "revise_with_feedback";
  status: "queued" | "running" | "patch_ready" | "review_ready" | "checks_running" | "awaiting_decision" | "awaiting_approval" | "approved" | "pushed" | "failed" | "cancelled" | "superseded" | "interrupted" | "recovery_required";
  requester: string;
  summary: string;
  parentRunId?: string | null;
  rootRunId?: string | null;
  supersededByRunId?: string | null;
  feedback?: AgentFeedback | null;
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
  diffHash?: string | null;
  pushedCommitSha?: string | null;
  selectedReviewThreads?: SelectedReviewThread[];
  dispositions?: ReviewDisposition[];
  replyDrafts?: ReplyDraft[];
  replyResults?: ReplyResult[];
  recoveryNote?: string | null;
  recoveryInspected?: boolean;
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
  rootRunId?: string | null;
  supersededByRunId?: string | null;
  workspacePath?: string | null;
  baseCommit?: string | null;
  diffHash?: string | null;
  pushedCommitSha?: string | null;
  createdAt: string;
  eventCount?: number;
  checkCount?: number;
  conflictCount?: number;
  resolvedConflictCount?: number;
  blockedCommandCount?: number;
  hasRebaseEvidence?: boolean;
  recoveryInspected?: boolean;
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

export type ConflictSection = {
  index: number;
  ours: BoundedText;
  theirs: BoundedText;
  result: BoundedText;
};

export type ConflictEvidence = {
  id: string;
  commitSha?: string | null;
  commitSubject?: string | null;
  filePath: string;
  ours: BoundedText;
  theirs: BoundedText;
  result: BoundedText;
  oursHunk?: BoundedText;
  theirsHunk?: BoundedText;
  resultHunk?: BoundedText;
  sections?: ConflictSection[];
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
  diffHash?: string | null;
  createdAt: string;
};

export type AgentFeedback = {
  instruction: string;
  reason?: string | null;
  createdAt: string;
};

export type PrNote = {
  id: string;
  text: string;
  author: string;
  createdAt: string;
  updatedAt: string;
};

export type PrAnnotations = {
  pullRequestId: string;
  tags: string[];
  notes: PrNote[];
};

export type ReviewThreadComment = { id: string; body: string; author: string; authorType: "human" | "bot" | "unknown"; createdAt: string; url?: string | null };
export type ReviewThread = {
  id: string;
  pullRequestId: string;
  repositoryFullName: string;
  pullRequestNumber: number;
  author: string;
  authorType: "human" | "bot" | "unknown";
  path?: string | null;
  line?: number | null;
  excerpt: string;
  body: string;
  diffHunk: string;
  createdAt: string;
  url?: string | null;
  isResolved: boolean;
  isOutdated: boolean;
  viewerCanReply: boolean;
  comments: ReviewThreadComment[];
};
export type ReviewThreadSnapshot = { pullRequestId: string; fetchedAt: string; stale: boolean; error?: string | null; threads: ReviewThread[] };
export type SelectedReviewThread = { threadId: string; body: string; diffHunk: string; path?: string | null; line?: number | null; author: string; authorType: "human" | "bot" | "unknown"; url?: string | null; capturedAt: string };
export type ReviewDisposition = { threadId: string; disposition: "addressed" | "not_addressed" | "needs_clarification"; explanation: string; relatedFiles: string[]; validationEvidence: string[] };
export type ReplyDraft = { id: string; threadId: string; body: string; diffHash: string; status: "draft" | "selected" | "posted" | "failed" | "ambiguous"; replyUrl?: string | null; error?: string | null; updatedAt: string };
export type ReplyResult = { draftId: string; threadId: string; status: "posted" | "failed" | "ambiguous" | "skipped"; replyUrl?: string | null; error?: string | null; actor?: string; commitSha?: string | null; createdAt: string };

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
  rootRunId?: string | null;
  supersededByRunId?: string | null;
  feedback?: AgentFeedback | null;
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
  diffHash?: string | null;
  pushedCommitSha?: string | null;
  selectedReviewThreads?: SelectedReviewThread[];
  dispositions?: ReviewDisposition[];
  replyDrafts?: ReplyDraft[];
  replyResults?: ReplyResult[];
  recoveryNote?: string | null;
  recoveryInspected?: boolean;
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
  prTags?: Record<string, string[]>;
  github?: GitHubSettings | null;
  searchSettings: SearchSettings;
  searchRuns: SearchRun[];
};

export type GitHubSyncResult = {
  syncedAt: string;
  repositoriesScanned: number;
  pullRequestsImported: number;
  errors: string[];
};

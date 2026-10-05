from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TeamMember(BaseModel):
    id: str
    displayName: str
    githubUsername: str
    gitAliases: list[str]
    emails: list[str]
    currentFocus: str
    responsibilities: str
    ownedRepos: list[str]
    ownedPaths: list[str]
    expertiseTags: list[str]
    timezone: str
    availability: Literal["active", "focus_mode", "ooo", "overloaded", "inactive"]


class PullRequest(BaseModel):
    id: str
    repository: str
    repositoryFullName: str | None = None
    headRepositoryFullName: str | None = None
    number: int
    title: str
    author: str
    ownerMemberId: str
    sourceBranch: str
    baseBranch: str
    state: Literal["open", "merged", "closed", "draft"]
    mergeable: Literal["mergeable", "conflicting", "unknown"]
    reviewState: Literal["approved", "changes_requested", "review_required", "commented"]
    unresolvedCommentCount: int
    requestedReviewers: list[str]
    checkState: Literal["passing", "failing", "pending", "not_run"]
    linkedIssueIds: list[str]
    changedFilesCount: int
    ageDays: int
    summary: str
    searchText: str


class RepositoryConfig(BaseModel):
    id: str
    owner: str
    name: str
    defaultBranch: str = "main"
    enabled: bool = True
    localPath: str | None = None
    requiredChecks: list[str] = ["git diff --check"]
    lastSyncedAt: str | None = None
    lastSyncStatus: str | None = None


class GitHubSettings(BaseModel):
    accessMode: Literal["contributor_token", "device_login", "github_app"] = "contributor_token"
    token: str | None = None
    username: str | None = None
    repositories: list[RepositoryConfig]
    lastSyncedAt: str | None = None


class GitHubSettingsPublic(BaseModel):
    accessMode: Literal["contributor_token", "device_login", "github_app"]
    hasToken: bool
    username: str | None = None
    repositories: list[RepositoryConfig]
    lastSyncedAt: str | None = None


class AgentBackend(BaseModel):
    id: Literal["opencode", "codex", "anthropic"]
    displayName: str
    adapterType: str
    endpoint: str
    defaultModel: str
    enabled: bool


class AgentSettings(BaseModel):
    runnerTimeoutSeconds: int = 600


class SearchSettings(BaseModel):
    backend: Literal["github", "gitcode"] = "github"
    gitcodeRepositories: list[str] = Field(default_factory=list)
    githubReadToken: str | None = None
    gitcodeReadToken: str | None = None


class SearchSettingsPublic(BaseModel):
    backend: Literal["github", "gitcode"] = "github"
    gitcodeRepositories: list[str] = Field(default_factory=list)
    githubReady: bool = False
    gitcodeReady: bool = False


class SearchLinkedItem(BaseModel):
    kind: Literal["pull_request", "issue"]
    number: int = Field(gt=0)
    url: str = Field(min_length=1, max_length=2000)


class SearchResult(BaseModel):
    source: Literal["github", "gitcode"]
    kind: Literal["pull_request", "issue"]
    repository: str
    number: int = Field(gt=0)
    url: str = Field(min_length=1, max_length=2000)
    originalTitle: str = Field(min_length=1, max_length=500)
    author: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1, max_length=80)
    match: Literal["confirmed", "semantic"]
    summary: dict[Literal["en", "zh"], str]
    reason: dict[Literal["en", "zh"], str]
    linkedItems: list[SearchLinkedItem] = Field(default_factory=list)


class SearchRun(BaseModel):
    id: str
    backendId: Literal["opencode", "codex", "anthropic"]
    searchBackend: Literal["github", "gitcode"]
    query: str
    kind: Literal["pull_requests", "issues"]
    repositoryIds: list[str]
    memberId: str | None = None
    locale: Literal["en", "zh"]
    status: Literal["queued", "running", "completed", "failed", "cancelled", "formatting_error", "interrupted"]
    summary: str
    results: list[SearchResult] = Field(default_factory=list)
    rawOutput: str | None = None
    errors: list[str] = Field(default_factory=list)
    events: list[dict[str, object]] = Field(default_factory=list)
    workspacePath: str | None = None
    createdAt: str
    completedAt: str | None = None


class SearchRunRequest(BaseModel):
    backendId: Literal["opencode", "codex", "anthropic"]
    query: str = Field(min_length=1, max_length=2000)
    kind: Literal["pull_requests", "issues"] = "pull_requests"
    repositoryIds: list[str] = Field(min_length=1, max_length=100)
    memberId: str | None = None
    locale: Literal["en", "zh"] = "en"


class UpdateSearchSettingsRequest(BaseModel):
    backend: Literal["github", "gitcode"] = "github"
    gitcodeRepositories: list[str] = Field(default_factory=list)
    githubReadToken: str | None = None
    gitcodeReadToken: str | None = None


class ApprovalRecord(BaseModel):
    id: str
    runId: str
    decision: Literal["approved", "rejected"]
    reviewer: str
    baseCommit: str | None = None
    diffHash: str | None = None
    createdAt: str


class AgentFeedback(BaseModel):
    instruction: str
    reason: str | None = None
    createdAt: str


class PrNote(BaseModel):
    id: str
    text: str
    author: str = "local user"
    createdAt: str
    updatedAt: str


class PrAnnotations(BaseModel):
    pullRequestId: str
    tags: list[str] = Field(default_factory=list)
    notes: list[PrNote] = Field(default_factory=list)


class ReviewThreadComment(BaseModel):
    id: str
    body: str
    author: str = "unknown"
    authorType: Literal["human", "bot", "unknown"] = "unknown"
    createdAt: str
    url: str | None = None


class ReviewThread(BaseModel):
    id: str
    pullRequestId: str
    repositoryFullName: str
    pullRequestNumber: int
    author: str = "unknown"
    authorType: Literal["human", "bot", "unknown"] = "unknown"
    path: str | None = None
    line: int | None = None
    excerpt: str = ""
    body: str = ""
    diffHunk: str = ""
    createdAt: str
    url: str | None = None
    isResolved: bool = False
    isOutdated: bool = False
    viewerCanReply: bool = False
    comments: list[ReviewThreadComment] = Field(default_factory=list)


class ReviewThreadSnapshot(BaseModel):
    pullRequestId: str
    fetchedAt: str
    stale: bool = False
    error: str | None = None
    threads: list[ReviewThread] = Field(default_factory=list)


class SelectedReviewThread(BaseModel):
    threadId: str
    body: str
    diffHunk: str = ""
    path: str | None = None
    line: int | None = None
    author: str = "unknown"
    authorType: Literal["human", "bot", "unknown"] = "unknown"
    url: str | None = None
    capturedAt: str


class ReviewDisposition(BaseModel):
    threadId: str
    disposition: Literal["addressed", "not_addressed", "needs_clarification"]
    explanation: str
    relatedFiles: list[str] = Field(default_factory=list)
    validationEvidence: list[str] = Field(default_factory=list)


class ReplyDraft(BaseModel):
    id: str
    threadId: str
    body: str
    diffHash: str
    status: Literal["draft", "selected", "posted", "failed", "ambiguous"] = "draft"
    replyUrl: str | None = None
    error: str | None = None
    updatedAt: str


class ReplyResult(BaseModel):
    draftId: str
    threadId: str
    status: Literal["posted", "failed", "ambiguous", "skipped"]
    replyUrl: str | None = None
    error: str | None = None
    actor: str = "local user"
    commitSha: str | None = None
    createdAt: str


class AgentRun(BaseModel):
    id: str
    backendId: str
    repository: str
    pullRequestId: str
    pullRequestNumber: int
    action: Literal["analyze", "rebase", "fix_conflicts", "address_review", "fix_checks", "review_patch", "revise_with_feedback"]
    status: Literal[
        "queued",
        "running",
        "patch_ready",
        "review_ready",
        "checks_running",
        "awaiting_decision",
        "awaiting_approval",
        "approved",
        "pushed",
        "failed",
        "cancelled",
        "superseded",
        "interrupted",
        "recovery_required",
    ]
    requester: str
    summary: str
    rootRunId: str | None = None
    parentRunId: str | None = None
    supersededByRunId: str | None = None
    feedback: AgentFeedback | None = None
    agentOutput: str | None = None
    backendSessionId: str | None = None
    workspacePath: str | None = None
    baseCommit: str | None = None
    events: list["AgentRunEvent"] = Field(default_factory=list)
    patchSummary: str | None = None
    diff: str | None = None
    checks: list["CheckResult"] = Field(default_factory=list)
    riskSummary: str | None = None
    approval: ApprovalRecord | None = None
    pushRef: str | None = None
    rebaseEvidence: "RebaseEvidence | None" = None
    diffHash: str | None = None
    pushedCommitSha: str | None = None
    selectedReviewThreads: list[SelectedReviewThread] = Field(default_factory=list)
    dispositions: list[ReviewDisposition] = Field(default_factory=list)
    replyDrafts: list[ReplyDraft] = Field(default_factory=list)
    replyResults: list[ReplyResult] = Field(default_factory=list)
    recoveryNote: str | None = None
    recoveryInspected: bool = False
    createdAt: str


class AgentRunEvent(BaseModel):
    sequence: int
    type: str
    message: str
    createdAt: str


class CheckResult(BaseModel):
    name: str
    status: Literal["passed", "failed", "skipped"]
    summary: str
    output: str = ""
    startedAt: str
    finishedAt: str


class BoundedText(BaseModel):
    text: str = ""
    truncated: bool = False
    originalLength: int = 0


class ConflictSection(BaseModel):
    index: int
    ours: BoundedText = Field(default_factory=BoundedText)
    theirs: BoundedText = Field(default_factory=BoundedText)
    result: BoundedText = Field(default_factory=BoundedText)


class ConflictEvidence(BaseModel):
    id: str
    commitSha: str | None = None
    commitSubject: str | None = None
    filePath: str
    ours: BoundedText = Field(default_factory=BoundedText)
    theirs: BoundedText = Field(default_factory=BoundedText)
    result: BoundedText = Field(default_factory=BoundedText)
    oursHunk: BoundedText = Field(default_factory=BoundedText)
    theirsHunk: BoundedText = Field(default_factory=BoundedText)
    resultHunk: BoundedText = Field(default_factory=BoundedText)
    sections: list[ConflictSection] = Field(default_factory=list)
    classification: Literal["ours", "theirs", "combined", "manual", "added", "deleted", "unknown"] = "unknown"
    validationState: Literal["passed", "failed", "unknown"] = "unknown"
    agentExplanation: str | None = None
    createdAt: str


class RebaseStage(BaseModel):
    sequence: int
    type: str
    message: str
    createdAt: str
    commitSha: str | None = None


class RebasePlan(BaseModel):
    strategy: Literal["standard", "drop_base_sync_merge"]
    targetRef: str
    upstreamRef: str | None = None
    command: str
    mergeCommit: str | None = None
    summary: str


class RebaseDecisionOption(BaseModel):
    id: Literal["drop_base_sync_merge", "manual"]
    label: str
    description: str
    recommended: bool = False


class RebaseDecision(BaseModel):
    question: str
    options: list[RebaseDecisionOption]
    selectedOption: Literal["drop_base_sync_merge", "manual"] | None = None


class RebaseEvidence(BaseModel):
    baseRef: str | None = None
    initialHead: str | None = None
    finalHead: str | None = None
    state: Literal["not_applicable", "running", "completed", "failed", "cancelled"] = "not_applicable"
    stages: list[RebaseStage] = Field(default_factory=list)
    conflicts: list[ConflictEvidence] = Field(default_factory=list)
    blockedCommands: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    plan: RebasePlan | None = None
    decision: RebaseDecision | None = None
    diff: BoundedText = Field(default_factory=BoundedText)
    transcript: BoundedText = Field(default_factory=BoundedText)


class ActionRecord(BaseModel):
    id: str
    kind: Literal["checkout", "agent_run"]
    repository: str
    pullRequestId: str
    pullRequestNumber: int
    action: str
    status: str
    summary: str
    rootRunId: str | None = None
    parentRunId: str | None = None
    supersededByRunId: str | None = None
    feedback: AgentFeedback | None = None
    agentOutput: str | None = None
    workspacePath: str | None = None
    baseCommit: str | None = None
    events: list[AgentRunEvent] = Field(default_factory=list)
    patchSummary: str | None = None
    diff: str | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    riskSummary: str | None = None
    approval: ApprovalRecord | None = None
    pushRef: str | None = None
    rebaseEvidence: RebaseEvidence | None = None
    diffHash: str | None = None
    pushedCommitSha: str | None = None
    selectedReviewThreads: list[SelectedReviewThread] = Field(default_factory=list)
    dispositions: list[ReviewDisposition] = Field(default_factory=list)
    replyDrafts: list[ReplyDraft] = Field(default_factory=list)
    replyResults: list[ReplyResult] = Field(default_factory=list)
    recoveryNote: str | None = None
    recoveryInspected: bool = False
    createdAt: str


class AgentRunSummary(BaseModel):
    id: str
    backendId: str
    repository: str
    pullRequestId: str
    pullRequestNumber: int
    action: str
    status: str
    requester: str
    summary: str
    rootRunId: str | None = None
    parentRunId: str | None = None
    supersededByRunId: str | None = None
    workspacePath: str | None = None
    baseCommit: str | None = None
    diffHash: str | None = None
    pushedCommitSha: str | None = None
    createdAt: str
    eventCount: int = 0
    checkCount: int = 0
    conflictCount: int = 0
    resolvedConflictCount: int = 0
    blockedCommandCount: int = 0
    hasRebaseEvidence: bool = False


class ActionSummary(BaseModel):
    id: str
    kind: Literal["checkout", "agent_run"]
    repository: str
    pullRequestId: str
    pullRequestNumber: int
    action: str
    status: str
    summary: str
    parentRunId: str | None = None
    rootRunId: str | None = None
    supersededByRunId: str | None = None
    workspacePath: str | None = None
    baseCommit: str | None = None
    createdAt: str
    eventCount: int = 0
    checkCount: int = 0
    conflictCount: int = 0
    resolvedConflictCount: int = 0
    blockedCommandCount: int = 0
    hasRebaseEvidence: bool = False
    pushRef: str | None = None
    diffHash: str | None = None
    pushedCommitSha: str | None = None
    recoveryInspected: bool = False


class ActivityEvent(BaseModel):
    id: str
    kind: str
    message: str
    actionId: str | None = None
    createdAt: str


class AppData(BaseModel):
    teamMembers: list[TeamMember]
    pullRequests: list[PullRequest]
    agentBackends: list[AgentBackend]
    agentSettings: AgentSettings = AgentSettings()
    agentRuns: list[AgentRunSummary]
    actions: list[ActionSummary] = []
    activity: list[ActivityEvent] = []
    approvals: list[ApprovalRecord] = []
    prTags: dict[str, list[str]] = Field(default_factory=dict)
    github: GitHubSettingsPublic | None = None
    searchSettings: SearchSettingsPublic = SearchSettingsPublic()
    searchRuns: list[SearchRun] = Field(default_factory=list)


class CreateAgentRunRequest(BaseModel):
    backendId: str
    pullRequestId: str
    action: Literal["analyze", "rebase", "fix_conflicts", "address_review", "fix_checks", "review_patch", "revise_with_feedback"]
    reviewThreadIds: list[str] = Field(default_factory=list)


class CreatePatchReviewRequest(BaseModel):
    backendId: str


class CreateRevisionRequest(BaseModel):
    backendId: str
    instruction: str = Field(min_length=1, max_length=12000)
    reason: str | None = Field(default=None, max_length=120)


class PostReviewRepliesRequest(BaseModel):
    replies: list[ReplyDraft] = Field(min_length=1, max_length=100)


class RecoveryInspectionRequest(BaseModel):
    confirmed: bool = False


class PushAgentRunRequest(BaseModel):
    target: Literal["mergeops_branch", "pr_branch"] = "pr_branch"


class UpdatePrTagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)


class CreatePrNoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


class UpdatePrNoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


class SelectRebaseDecisionRequest(BaseModel):
    optionId: Literal["drop_base_sync_merge", "manual"]


class UpdateAgentSettingsRequest(BaseModel):
    runnerTimeoutSeconds: int = 600


class CreateCheckoutRequest(BaseModel):
    pullRequestId: str


class CheckoutResult(BaseModel):
    pullRequestId: str
    status: Literal["ready", "failed"]
    workspacePath: str | None = None
    baseCommit: str | None = None
    summary: str
    action: ActionRecord


class CreateTeamMemberRequest(BaseModel):
    displayName: str
    githubUsername: str
    gitAliases: list[str] = []
    emails: list[str] = []
    currentFocus: str = ""
    responsibilities: str = ""
    ownedRepos: list[str] = []
    ownedPaths: list[str] = []
    expertiseTags: list[str] = []
    timezone: str = "Asia/Jerusalem"
    availability: Literal["active", "focus_mode", "ooo", "overloaded", "inactive"] = "active"


class UpdateTeamMemberRequest(BaseModel):
    displayName: str | None = None
    githubUsername: str | None = None
    gitAliases: list[str] | None = None
    emails: list[str] | None = None
    currentFocus: str | None = None
    responsibilities: str | None = None
    ownedRepos: list[str] | None = None
    ownedPaths: list[str] | None = None
    expertiseTags: list[str] | None = None
    timezone: str | None = None
    availability: Literal["active", "focus_mode", "ooo", "overloaded", "inactive"] | None = None


class UpdateGitHubSettingsRequest(BaseModel):
    accessMode: Literal["contributor_token", "device_login", "github_app"] | None = None
    token: str | None = None
    username: str | None = None
    repositories: list[RepositoryConfig] | None = None


class GitHubSyncResult(BaseModel):
    syncedAt: str
    repositoriesScanned: int
    pullRequestsImported: int
    errors: list[str]

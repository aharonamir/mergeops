from typing import Literal

from pydantic import BaseModel


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


class ApprovalRecord(BaseModel):
    id: str
    runId: str
    decision: Literal["approved", "rejected"]
    reviewer: str
    baseCommit: str | None = None
    createdAt: str


class AgentRun(BaseModel):
    id: str
    backendId: str
    repository: str
    pullRequestId: str
    pullRequestNumber: int
    action: Literal["analyze", "rebase", "fix_conflicts", "address_review", "fix_checks", "review_patch"]
    status: Literal[
        "queued",
        "running",
        "patch_ready",
        "review_ready",
        "checks_running",
        "awaiting_approval",
        "approved",
        "pushed",
        "failed",
        "cancelled",
    ]
    requester: str
    summary: str
    parentRunId: str | None = None
    agentOutput: str | None = None
    backendSessionId: str | None = None
    workspacePath: str | None = None
    baseCommit: str | None = None
    events: list["AgentRunEvent"] = []
    patchSummary: str | None = None
    diff: str | None = None
    checks: list["CheckResult"] = []
    riskSummary: str | None = None
    approval: ApprovalRecord | None = None
    pushRef: str | None = None
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


class ActionRecord(BaseModel):
    id: str
    kind: Literal["checkout", "agent_run"]
    repository: str
    pullRequestId: str
    pullRequestNumber: int
    action: str
    status: str
    summary: str
    parentRunId: str | None = None
    agentOutput: str | None = None
    workspacePath: str | None = None
    baseCommit: str | None = None
    events: list[AgentRunEvent] = []
    patchSummary: str | None = None
    diff: str | None = None
    checks: list[CheckResult] = []
    riskSummary: str | None = None
    approval: ApprovalRecord | None = None
    pushRef: str | None = None
    createdAt: str


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
    agentRuns: list[AgentRun]
    actions: list[ActionRecord] = []
    activity: list[ActivityEvent] = []
    approvals: list[ApprovalRecord] = []
    github: GitHubSettingsPublic | None = None


class CreateAgentRunRequest(BaseModel):
    backendId: str
    pullRequestId: str
    action: Literal["analyze", "rebase", "fix_conflicts", "address_review", "fix_checks", "review_patch"]


class CreatePatchReviewRequest(BaseModel):
    backendId: str


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

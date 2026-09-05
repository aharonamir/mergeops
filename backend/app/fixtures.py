from datetime import datetime, timezone

from .models import AgentBackend, AgentRun, AgentRunEvent, AppData, CheckResult, GitHubSettings, GitHubSettingsPublic, PullRequest, RepositoryConfig, TeamMember


team_members = [
    TeamMember(
        id="lior",
        displayName="Lior Cohen",
        githubUsername="liorco",
        gitAliases=["lior@company.dev", "lcohen"],
        emails=["lior@company.dev"],
        currentFocus="Billing API extraction",
        responsibilities="Payments, API contracts, release safety",
        ownedRepos=["agent-core", "perfrouter"],
        ownedPaths=["services/billing", "routing"],
        expertiseTags=["backend", "payments", "python"],
        timezone="Asia/Jerusalem",
        availability="active",
    ),
    TeamMember(
        id="maya",
        displayName="Maya Levi",
        githubUsername="mayalevi",
        gitAliases=["maya@company.dev"],
        emails=["maya@company.dev"],
        currentFocus="Reviewing search index rollout",
        responsibilities="Frontend workflows, bilingual search UX",
        ownedRepos=["jiuwenswarm-ide", "token-optimizer"],
        ownedPaths=["frontend", "search"],
        expertiseTags=["frontend", "search", "typescript"],
        timezone="Asia/Jerusalem",
        availability="focus_mode",
    ),
    TeamMember(
        id="noam",
        displayName="Noam Bar",
        githubUsername="noambar",
        gitAliases=["nbar", "noam@company.dev"],
        emails=["noam@company.dev"],
        currentFocus="CI stability and Docker cache fixes",
        responsibilities="Infra, CI, local developer tooling",
        ownedRepos=["agent-worx", "docs"],
        ownedPaths=["deploy", ".github/workflows"],
        expertiseTags=["infra", "ci", "docker"],
        timezone="Europe/Berlin",
        availability="overloaded",
    ),
    TeamMember(
        id="dana",
        displayName="Dana Katz",
        githubUsername="danak",
        gitAliases=["dana@company.dev"],
        emails=["dana@company.dev"],
        currentFocus="Agent permission model",
        responsibilities="Security review, agent guardrails",
        ownedRepos=["WildClawBench", "agent-core"],
        ownedPaths=["security", "permissions"],
        expertiseTags=["security", "agents", "reviews"],
        timezone="Asia/Jerusalem",
        availability="active",
    ),
]

pull_requests = [
    PullRequest(
        id="pr-842",
        repository="agent-core",
        repositoryFullName="your-org/agent-core",
        number=842,
        title="Rework session permission prompts for opencode bridge",
        author="danak",
        ownerMemberId="dana",
        sourceBranch="feature/session-permissions",
        baseBranch="main",
        state="open",
        mergeable="conflicting",
        reviewState="commented",
        unresolvedCommentCount=9,
        requestedReviewers=["liorco"],
        checkState="failing",
        linkedIssueIds=["SEC-118"],
        changedFilesCount=12,
        ageDays=4,
        summary="Touches approval gates and session permission handoff. Conflict in permission policy tests.",
        searchText="permission approval הרשאות אישור opencode",
    ),
    PullRequest(
        id="pr-317",
        repository="token-optimizer",
        repositoryFullName="your-org/token-optimizer",
        number=317,
        title="Add Hebrew/English issue expansion to repository search",
        author="mayalevi",
        ownerMemberId="maya",
        sourceBranch="search/bilingual-expansion",
        baseBranch="main",
        state="open",
        mergeable="mergeable",
        reviewState="review_required",
        unresolvedCommentCount=5,
        requestedReviewers=["liorco"],
        checkState="passing",
        linkedIssueIds=["SRCH-42"],
        changedFilesCount=8,
        ageDays=2,
        summary="Adds bilingual query normalization and issue/PR result grouping.",
        searchText="bilingual search hebrew english חיפוש עברית issues prs",
    ),
    PullRequest(
        id="pr-1055",
        repository="jiuwenswarm-memtier",
        repositoryFullName="your-org/jiuwenswarm-memtier",
        number=1055,
        title="Stabilize memtier docker compose harness",
        author="noambar",
        ownerMemberId="noam",
        sourceBranch="infra/memtier-compose",
        baseBranch="main",
        state="open",
        mergeable="unknown",
        reviewState="approved",
        unresolvedCommentCount=1,
        requestedReviewers=[],
        checkState="failing",
        linkedIssueIds=["CI-77"],
        changedFilesCount=5,
        ageDays=6,
        summary="Flaky redis service startup; failing on cold cache path.",
        searchText="docker compose redis ci failing בדיקות",
    ),
    PullRequest(
        id="pr-229",
        repository="perfrouter",
        repositoryFullName="your-org/perfrouter",
        number=229,
        title="Extract billing router from benchmark runner",
        author="liorco",
        ownerMemberId="lior",
        sourceBranch="billing/router-extract",
        baseBranch="main",
        state="open",
        mergeable="mergeable",
        reviewState="approved",
        unresolvedCommentCount=0,
        requestedReviewers=[],
        checkState="passing",
        linkedIssueIds=["BILL-21"],
        changedFilesCount=4,
        ageDays=1,
        summary="Small extraction with test coverage and clean branch.",
        searchText="billing router ready merge תשלום",
    ),
]

agent_backends = [
    AgentBackend(
        id="opencode",
        displayName="opencode",
        adapterType="@opencode-ai/sdk",
        endpoint="local TypeScript runner",
        defaultModel="team default",
        enabled=True,
    ),
    AgentBackend(
        id="codex",
        displayName="Codex",
        adapterType="Codex agent adapter",
        endpoint="local codex runner",
        defaultModel="gpt-5-codex",
        enabled=True,
    ),
    AgentBackend(
        id="anthropic",
        displayName="Anthropic",
        adapterType="Anthropic agent adapter",
        endpoint="Anthropic API / internal runner",
        defaultModel="Claude team default",
        enabled=True,
    ),
]

agent_runs = [
    AgentRun(
        id="run-842",
        backendId="opencode",
        repository="agent-core",
        pullRequestId="pr-842",
        pullRequestNumber=842,
        action="fix_conflicts",
        status="awaiting_approval",
        requester="amir",
        summary="Conflict analysis prepared; patch plan identifies 3 files to reconcile.",
        events=[AgentRunEvent(sequence=1, type="patch_ready", message="Patch and check results are ready for human approval.", createdAt="2026-09-03T12:00:00Z")],
        patchSummary="3 files changed; conflict markers reconciled in the isolated workspace.",
        diff="diff --git a/permissions/policy.ts b/permissions/policy.ts\n+updated approval handling",
        checks=[CheckResult(name="git diff --check", status="passed", summary="Check passed.", startedAt="2026-09-03T12:01:00Z", finishedAt="2026-09-03T12:01:02Z")],
        riskSummary="Medium risk: patch requires human review.",
        createdAt="2026-09-03T12:00:00Z",
    )
]

github_settings = GitHubSettings(
    accessMode="contributor_token",
    token=None,
    username=None,
    repositories=[
        RepositoryConfig(id="agent-core", owner="your-org", name="agent-core"),
        RepositoryConfig(id="token-optimizer", owner="your-org", name="token-optimizer"),
    ],
    lastSyncedAt=None,
)


def app_data() -> AppData:
    return AppData(
        teamMembers=team_members,
        pullRequests=pull_requests,
        agentBackends=agent_backends,
        agentRuns=agent_runs,
        github=GitHubSettingsPublic(
            accessMode=github_settings.accessMode,
            hasToken=bool(github_settings.token),
            username=github_settings.username,
            repositories=github_settings.repositories,
            lastSyncedAt=github_settings.lastSyncedAt,
        ),
    )


def create_agent_run(backend_id: str, pull_request_id: str, action: str) -> AgentRun:
    pull_request = next((item for item in pull_requests if item.id == pull_request_id), None)
    if pull_request is None:
        raise ValueError("Unknown pull request")

    run = AgentRun(
        id=f"run-{len(agent_runs) + 1}",
        backendId=backend_id,
        repository=pull_request.repository,
        pullRequestId=pull_request.id,
        pullRequestNumber=pull_request.number,
        action=action,
        status="awaiting_approval",
        requester="local user",
        summary=f"Queued {action.replace('_', ' ')} run. No push will happen until approval.",
        createdAt=datetime.now(timezone.utc).isoformat(),
    )
    agent_runs.insert(0, run)
    return run

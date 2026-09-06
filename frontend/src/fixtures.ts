import type { AppData } from "./types";

export const fixtureData: AppData = {
  teamMembers: [
    {
      id: "lior",
      displayName: "Lior Cohen",
      githubUsername: "liorco",
      gitAliases: ["lior@company.dev", "lcohen"],
      emails: ["lior@company.dev"],
      currentFocus: "Billing API extraction",
      responsibilities: "Payments, API contracts, release safety",
      ownedRepos: ["agent-core", "perfrouter"],
      ownedPaths: ["services/billing", "routing"],
      expertiseTags: ["backend", "payments", "python"],
      timezone: "Asia/Jerusalem",
      availability: "active"
    },
    {
      id: "maya",
      displayName: "Maya Levi",
      githubUsername: "mayalevi",
      gitAliases: ["maya@company.dev"],
      emails: ["maya@company.dev"],
      currentFocus: "Reviewing search index rollout",
      responsibilities: "Frontend workflows, bilingual search UX",
      ownedRepos: ["jiuwenswarm-ide", "token-optimizer"],
      ownedPaths: ["frontend", "search"],
      expertiseTags: ["frontend", "search", "typescript"],
      timezone: "Asia/Jerusalem",
      availability: "focus_mode"
    },
    {
      id: "noam",
      displayName: "Noam Bar",
      githubUsername: "noambar",
      gitAliases: ["nbar", "noam@company.dev"],
      emails: ["noam@company.dev"],
      currentFocus: "CI stability and Docker cache fixes",
      responsibilities: "Infra, CI, local developer tooling",
      ownedRepos: ["agent-worx", "docs"],
      ownedPaths: ["deploy", ".github/workflows"],
      expertiseTags: ["infra", "ci", "docker"],
      timezone: "Europe/Berlin",
      availability: "overloaded"
    },
    {
      id: "dana",
      displayName: "Dana Katz",
      githubUsername: "danak",
      gitAliases: ["dana@company.dev"],
      emails: ["dana@company.dev"],
      currentFocus: "Agent permission model",
      responsibilities: "Security review, agent guardrails",
      ownedRepos: ["WildClawBench", "agent-core"],
      ownedPaths: ["security", "permissions"],
      expertiseTags: ["security", "agents", "reviews"],
      timezone: "Asia/Jerusalem",
      availability: "active"
    }
  ],
  pullRequests: [
    {
      id: "pr-842",
      repository: "agent-core",
      repositoryFullName: "your-org/agent-core",
      number: 842,
      title: "Rework session permission prompts for opencode bridge",
      author: "danak",
      ownerMemberId: "dana",
      sourceBranch: "feature/session-permissions",
      baseBranch: "main",
      state: "open",
      mergeable: "conflicting",
      reviewState: "commented",
      unresolvedCommentCount: 9,
      requestedReviewers: ["liorco"],
      checkState: "failing",
      linkedIssueIds: ["SEC-118"],
      changedFilesCount: 12,
      ageDays: 4,
      summary: "Touches approval gates and session permission handoff. Conflict in permission policy tests.",
      searchText: "permission approval הרשאות אישור opencode"
    },
    {
      id: "pr-317",
      repository: "token-optimizer",
      repositoryFullName: "your-org/token-optimizer",
      number: 317,
      title: "Add Hebrew/English issue expansion to repository search",
      author: "mayalevi",
      ownerMemberId: "maya",
      sourceBranch: "search/bilingual-expansion",
      baseBranch: "main",
      state: "open",
      mergeable: "mergeable",
      reviewState: "review_required",
      unresolvedCommentCount: 5,
      requestedReviewers: ["liorco"],
      checkState: "passing",
      linkedIssueIds: ["SRCH-42"],
      changedFilesCount: 8,
      ageDays: 2,
      summary: "Adds bilingual query normalization and issue/PR result grouping.",
      searchText: "bilingual search hebrew english חיפוש עברית issues prs"
    },
    {
      id: "pr-1055",
      repository: "jiuwenswarm-memtier",
      repositoryFullName: "your-org/jiuwenswarm-memtier",
      number: 1055,
      title: "Stabilize memtier docker compose harness",
      author: "noambar",
      ownerMemberId: "noam",
      sourceBranch: "infra/memtier-compose",
      baseBranch: "main",
      state: "open",
      mergeable: "unknown",
      reviewState: "approved",
      unresolvedCommentCount: 1,
      requestedReviewers: [],
      checkState: "failing",
      linkedIssueIds: ["CI-77"],
      changedFilesCount: 5,
      ageDays: 6,
      summary: "Flaky redis service startup; failing on cold cache path.",
      searchText: "docker compose redis ci failing בדיקות"
    },
    {
      id: "pr-229",
      repository: "perfrouter",
      repositoryFullName: "your-org/perfrouter",
      number: 229,
      title: "Extract billing router from benchmark runner",
      author: "liorco",
      ownerMemberId: "lior",
      sourceBranch: "billing/router-extract",
      baseBranch: "main",
      state: "open",
      mergeable: "mergeable",
      reviewState: "approved",
      unresolvedCommentCount: 0,
      requestedReviewers: [],
      checkState: "passing",
      linkedIssueIds: ["BILL-21"],
      changedFilesCount: 4,
      ageDays: 1,
      summary: "Small extraction with test coverage and clean branch.",
      searchText: "billing router ready merge תשלום"
    }
  ],
  agentBackends: [
    {
      id: "opencode",
      displayName: "opencode",
      adapterType: "@opencode-ai/sdk",
      endpoint: "local SDK process (dynamic port)",
      defaultModel: "team default",
      enabled: true
    },
    {
      id: "codex",
      displayName: "Codex",
      adapterType: "Codex agent adapter",
      endpoint: "local codex runner",
      defaultModel: "gpt-5-codex",
      enabled: true
    },
    {
      id: "anthropic",
      displayName: "Anthropic",
      adapterType: "Anthropic agent adapter",
      endpoint: "Anthropic API / internal runner",
      defaultModel: "Claude team default",
      enabled: true
    }
  ],
  agentSettings: {
    runnerTimeoutSeconds: 600
  },
  agentRuns: [
    {
      id: "run-842",
      backendId: "opencode",
      repository: "agent-core",
      pullRequestId: "pr-842",
      pullRequestNumber: 842,
      action: "fix_conflicts",
      status: "awaiting_approval",
      requester: "amir",
      summary: "Conflict analysis prepared; patch plan identifies 3 files to reconcile.",
      createdAt: "2026-09-03T12:00:00Z"
    }
  ],
  github: {
    accessMode: "contributor_token",
    hasToken: false,
    username: null,
    repositories: [
      {
        id: "agent-core",
        owner: "your-org",
        name: "agent-core",
        defaultBranch: "main",
        enabled: true,
        lastSyncedAt: null,
        lastSyncStatus: null
      },
      {
        id: "token-optimizer",
        owner: "your-org",
        name: "token-optimizer",
        defaultBranch: "main",
        enabled: true,
        lastSyncedAt: null,
        lastSyncStatus: null
      }
    ],
    lastSyncedAt: null
  }
};

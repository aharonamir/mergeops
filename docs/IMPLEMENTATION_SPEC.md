# MergeOps Implementation Spec

## Product Goal

MergeOps is a PR-first SDLC cockpit for a team lead managing one team across many repositories. It combines GitHub pull request state, team ownership context, bilingual issue/PR search, CI signals, and backend agent SDK remediation into one operational dashboard.

The primary workflow is not passive reporting. The lead identifies work that needs intervention, starts an agent-assisted remediation run, reviews the generated patch and check result, then explicitly approves any push.

## V1 Scope

V1 must ship a working PR cockpit with real data and an approval-gated remediation loop.

Included:
- GitHub repository and PR ingestion.
- Team member configuration with GitHub IDs, aliases, responsibilities, ownership, expertise, focus, timezone, and availability.
- Cross-repo PR intervention queue.
- PR detail drawer with review state, checks, mergeability, branch freshness, linked issues, comments, and owner context.
- Agent backend adapter selection: `opencode`, `codex`, `anthropic`.
- Agent run creation for selected PRs.
- Human approval before push.
- Agent run history and audit trail.
- Bilingual search entry point for issues and PRs.
- System/light/dark theme preference.

Deferred:
- Full release management.
- Multi-team hierarchy.
- Capacity planning trends.
- Auto-merge policy beyond explicit approval.
- Deep analytics beyond immediate operational counts.
- Non-GitHub providers.

## Core Screens

### PR Cockpit

The default screen is an intervention queue ordered by action urgency:
1. merge conflicts
2. failing required checks
3. unresolved review comments
4. stale branch
5. waiting for review
6. ready to merge

Required filters:
- repository
- owner/team member
- status group
- reviewer
- age
- checks
- mergeability
- saved view
- bilingual search query

Required PR row fields:
- priority/status
- title
- repository
- PR number
- source branch
- base branch
- author
- assigned owner
- requested reviewers
- approvals
- unresolved comments
- check state
- mergeability
- branch freshness
- age
- next action

### PR Detail Drawer

The drawer must support fast triage without navigation away from the queue.

Sections:
- PR summary and metadata.
- Operational state: review, checks, age, comments, mergeability, branch freshness.
- Owner context: current focus, responsibilities, expertise, availability.
- Linked issues and bilingual search matches.
- Review comments grouped by thread.
- Files changed summary.
- Agent remediation plan.
- Approval gate.

Primary actions:
- prepare fix
- prepare rebase
- request review
- hold PR
- approve push, only after patch and checks are available

### Team Workspace

The team workspace stores the context that makes PR state actionable.

Team member fields:
- display name
- GitHub username
- Git aliases and commit emails
- current focus
- responsibilities
- owned repositories
- owned paths or service areas
- reviewer expertise tags
- timezone
- working hours
- availability
- lead-only notes
- active/inactive state

The cockpit should use this data for filtering, owner display, and intervention ranking.

### Agent Runs

Agent Runs shows remediation sessions across backends.

Fields:
- run ID
- backend adapter
- repository
- PR
- branch
- requested action
- requester
- status
- current step
- generated patch ref
- checks result
- approval state
- approver
- timestamps
- failure reason

### Settings

Settings sections:
- Team
- Repositories
- Integrations
- Automation Policy
- Search
- Preferences
- Audit and Retention

## Architecture

Use a frontend/backend split. The frontend should never call GitHub, CI providers, or agent SDKs directly with privileged credentials.

Recommended production shape:
- Web frontend: dashboard UI.
- API server: auth, settings, data access, orchestration, approvals.
- Worker: GitHub sync, CI sync, indexing, agent run execution.
- Database: durable state and audit trail.
- Queue: long-running sync and remediation jobs.
- Adapter layer: backend agent SDK abstraction.

Chosen stack:
- Frontend: React/Vite with TypeScript.
- API/server: Python/FastAPI.
- Database: Postgres.
- Queue: Redis-backed worker queue.
- Auth: GitHub OAuth or GitHub device login for contributor-owned access.

Deployment target: local-only first build. The app should run on the lead's machine and connect to local repository checkouts, local agent SDK runtimes, and GitHub using user-authenticated access.

## Data Model

### TeamMember

```ts
type TeamMember = {
  id: string
  displayName: string
  githubUsername: string
  gitAliases: string[]
  emails: string[]
  currentFocus: string
  responsibilities: string
  ownedRepos: string[]
  ownedPaths: OwnedPath[]
  expertiseTags: string[]
  timezone: string
  workingHours?: WorkingHours
  availability: "active" | "focus_mode" | "ooo" | "overloaded" | "inactive"
  leadNotes?: string
  createdAt: string
  updatedAt: string
}
```

### Repository

```ts
type Repository = {
  id: string
  provider: "github"
  owner: string
  name: string
  defaultBranch: string
  included: boolean
  archived: boolean
  groups: string[]
  requiredChecks: string[]
  stalePrDays: number
}
```

### PullRequest

```ts
type PullRequest = {
  id: string
  provider: "github"
  repositoryId: string
  number: number
  title: string
  author: string
  ownerMemberId?: string
  sourceBranch: string
  baseBranch: string
  state: "open" | "merged" | "closed" | "draft"
  mergeable: "mergeable" | "conflicting" | "unknown"
  reviewState: "approved" | "changes_requested" | "review_required" | "commented"
  unresolvedCommentCount: number
  requestedReviewers: string[]
  checkState: "passing" | "failing" | "pending" | "not_run"
  labels: string[]
  linkedIssueIds: string[]
  changedFilesCount: number
  additions: number
  deletions: number
  createdAt: string
  updatedAt: string
}
```

### AgentBackend

```ts
type AgentBackend = {
  id: "opencode" | "codex" | "anthropic" | string
  displayName: string
  adapterType: string
  endpoint?: string
  defaultModel?: string
  enabled: boolean
  credentialsRef?: string
}
```

### AgentRun

```ts
type AgentRun = {
  id: string
  backendId: string
  repositoryId: string
  pullRequestId: string
  action: "analyze" | "rebase" | "fix_conflicts" | "address_review" | "fix_checks"
  status: "queued" | "running" | "patch_ready" | "checks_running" | "awaiting_approval" | "approved" | "pushed" | "failed" | "cancelled"
  requesterId: string
  approverId?: string
  sessionRef?: string
  branchName?: string
  patchRef?: string
  checkRunRef?: string
  riskLevel?: "low" | "medium" | "high"
  summary?: string
  failureReason?: string
  createdAt: string
  updatedAt: string
}
```

### Approval

```ts
type Approval = {
  id: string
  agentRunId: string
  requestedBy: string
  approvedBy?: string
  state: "pending" | "approved" | "rejected"
  requiredChecks: string[]
  checksPassed: boolean
  patchReviewed: boolean
  decisionReason?: string
  createdAt: string
  decidedAt?: string
}
```

## Backend Agent Adapter Contract

All backend SDKs must conform to one dashboard-facing interface. The UI and workflow should not change when switching from opencode to Codex or Anthropic.

```ts
interface AgentAdapter {
  id: string
  displayName: string

  health(): Promise<AgentHealth>

  createRun(input: CreateAgentRunInput): Promise<AgentRunRef>

  streamEvents(runRef: AgentRunRef): AsyncIterable<AgentEvent>

  getStatus(runRef: AgentRunRef): Promise<AgentRunStatus>

  getPatch(runRef: AgentRunRef): Promise<PatchSummary>

  runChecks(runRef: AgentRunRef): Promise<CheckSummary>

  requestPush(input: PushRequestInput): Promise<PushPlan>

  pushAfterApproval(input: ApprovedPushInput): Promise<PushResult>

  cancel(runRef: AgentRunRef): Promise<void>
}
```

Adapter responsibilities:
- map dashboard action to backend-specific session/run prompt
- provide streamed progress events
- return a patch summary
- expose changed files and risk summary
- run or delegate tests/checks
- never push without an approval token from the API server
- record backend session IDs for audit

## opencode Adapter Notes

Current opencode docs indicate:
- A running server can expose an API.
- The SDK can connect to a server with `baseUrl`.
- Sessions can be created for projects.
- Messages can be sent to sessions.
- Events can be streamed.
- File status and file content/patches can be inspected.
- Permission workflows exist.

The opencode adapter should map a MergeOps remediation run to an opencode project/session rooted at the repository checkout.

## GitHub Integration

V1 must assume the team are contributors, not repository or organization owners. Do not require a GitHub App installation for the core product.

Use user-authenticated GitHub OAuth or GitHub device login:
- each connected user grants access to repositories they can already see
- read visibility is limited by the connected users' permissions
- write actions happen as the approving GitHub user
- push is possible only when that user can push to the branch or fork
- audit events must record the GitHub user whose token performed the action

A GitHub App can remain an optional later integration if repository owners agree to install it.

Required GitHub data:
- repositories
- pull requests
- reviews
- review threads/comments
- check suites/check runs
- branch refs
- mergeability
- labels
- linked issues
- CODEOWNERS when available

Ingestion:
- polling-first for V1 because contributors may not be able to configure webhooks
- scheduled reconciliation for freshness
- manual sync button per repo
- optional webhook-first mode only when a GitHub App is installed later

Write actions:
- create remediation branch
- push commits only after approval
- optionally post PR comment with generated summary
- never bypass protected branch rules

## CI Integration

V1 can start with GitHub Actions via GitHub check runs.

The system must distinguish:
- failing required checks
- failing optional checks
- pending checks
- missing checks
- checks not run because branch is stale or conflicted

## Bilingual Search Integration

The dedicated Search page accepts English and Simplified Chinese queries and
searches PRs or issues through the selected GitHub or GitCode skill. GitHub is
the default search service. Search jobs run in temporary isolated workspaces;
they are read-only and do not use the PR patch approval flow.

The configured code agent may be Codex, Claude, or OpenCode. Each SDK adapter
extracts its own final assistant response, then a shared validator normalizes
and validates the versioned result schema before the UI renders anything.
Search explanations carry both English and Simplified Chinese so the UX language
toggle can change their display without rerunning the search. A malformed
response becomes a visible formatting error with bounded raw output available
for diagnosis.

Search scope comes from repositories configured for the selected service, with
optional author filtering. Search service credentials are separate,
read-only tokens; never pass the GitHub remediation/push credential to a search
agent. The Settings → Search section stores the service choice and its
credentials, while the query and scope remain on the Search page.

## Approval Policy

Default policy:
- Agent may analyze PRs.
- Agent may create or update a fix branch.
- Agent may prepare patches.
- Agent may run tests/checks.
- Push requires human approval.
- Approval requires a visible diff summary and check result.
- High-risk changes require explicit second confirmation or maintainer review.

Approval screen must show:
- PR
- backend
- action requested
- branch
- changed files
- patch summary
- test/check result
- risk level
- generated explanation
- requester
- approver
- timestamp

## API Surface

Minimum API endpoints:

```http
GET /api/me
GET /api/team-members
POST /api/team-members
PATCH /api/team-members/:id

GET /api/repositories
POST /api/repositories/sync

GET /api/pull-requests
GET /api/pull-requests/:id

GET /api/search?q=...

GET /api/agent-backends
PATCH /api/settings/agent-backend

POST /api/agent-runs
GET /api/agent-runs
GET /api/agent-runs/:id
GET /api/agent-runs/:id/events
POST /api/agent-runs/:id/cancel

POST /api/agent-runs/:id/approval
POST /api/agent-runs/:id/push

GET /api/settings
PATCH /api/settings
GET /api/audit-log
```

## Security Requirements

- Store credentials server-side only.
- Encrypt tokens or use a managed secret store.
- Never expose GitHub tokens, agent API keys, or CI tokens to the browser.
- Every write action must have an audit event.
- Push action requires an approval record.
- Redact secrets from agent logs and session transcripts.
- Respect repository permissions and protected branch rules.
- Keep agent workspace paths constrained to configured repositories.
- For local-only v1, bind services to localhost by default.
- Store local secrets outside the frontend project tree.
- Make local repository paths explicit, allowlisted, and editable in settings.

## V1 Milestones

### Milestone 1: Product Shell

- Convert static prototype to chosen app stack.
- Preserve current layout: cockpit, team workspace, agent runs, settings.
- Implement persisted theme and backend adapter preference.
- Replace synthetic data layer with typed fixtures.
- Run locally with separate Vite and FastAPI dev servers.

### Milestone 2: GitHub Read Integration

- Add GitHub OAuth or device login.
- Sync repositories and PRs.
- Display live PR queue.
- Display PR detail drawer with reviews, checks, comments, mergeability.

### Milestone 3: Team Workspace

- Persist team members.
- Map GitHub users and aliases to team members.
- Add ownership and expertise fields.
- Use team context in filters and queue ranking.

### Milestone 4: Agent Adapter Foundation

- Define adapter interface.
- Implement opencode adapter first.
- Add placeholder Codex and Anthropic adapters behind the same interface.
- Create agent run records and event streaming.

### Milestone 5: Approval-Gated Remediation

- Start remediation run from PR drawer.
- Prepare branch/patch.
- Run checks.
- Show approval screen.
- Push only after approval.
- Record audit trail.

### Milestone 6: Bilingual Search

- Add GitHub/GitCode search service settings and isolated persisted search runs.
- Wrap the four existing PR/issue skills with a shared bilingual result schema.
- Add the dedicated Search page with repository/author scope and collapsible
  source-linked results.
- Normalize Codex, Claude, and OpenCode responses before rendering.

## Open Decisions

- Auth mode details: OAuth app versus GitHub device login.
- Bilingual search skill interface: CLI, MCP, HTTP, or library.
- CI providers beyond GitHub Actions.
- Exact approval roles and escalation rules.
- Whether generated patches should be stored as files, database records, or Git branches only.
- Whether repository owners will later install a GitHub App for webhook and installation-token support.

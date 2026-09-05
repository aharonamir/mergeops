# MergeOps Roadmap

## Current State

`mergeops/` contains the original static prototype plus the first React/Vite and FastAPI local-only scaffold. It validates product shape, information architecture, core screens, theme behavior, team workspace fields, backend agent SDK selection, and fixture-backed API flow.

## Review Blockers

### P2: Avoid selecting local paths by bare repo name

Status: Resolved. Manual UI verification remains pending.

Current risk: live GitHub sync stores PRs with `repository` as the bare repo name
only, while repository settings can contain multiple entries with the same name
under different owners. `LocalJsonStore._repository_config()` can therefore pick
the first matching `name` and launch an agent run in the wrong local checkout.

Required fix:
- Preserve an unambiguous repository key on every synced PR, preferably
  `repositoryId` or `repositoryFullName` using `owner/name`.
- Match agent run local paths by that key, not by bare `repository.name`.
- Keep display text free to show the short repo name, but never use that short
  name as the execution lookup key.
- Add a regression test with two configured repositories sharing the same
  `name` and different `owner`/`localPath` values.

Until this is fixed, agent execution should stay guarded by explicit local path
configuration and should not be considered safe for duplicate repository names.

## Recommended Next Build Path

### Slice 1: App Foundation

Goal: turn the prototype into a typed app without changing product behavior.

Deliverables:
- Initialize React/Vite frontend. Done.
- Initialize Python/FastAPI backend. Done.
- Port current UI into components. Started.
- Add typed fixture data. Done.
- Add route structure for cockpit, team, agent runs, and settings.
- Keep theme and backend preference persisted.

Exit criteria:
- Prototype behavior preserved.
- No real credentials required.
- Components ready to connect to APIs.

### Slice 2: GitHub Read Model

Goal: replace PR fixtures with live GitHub read data.

Deliverables:
- GitHub OAuth or device login setup.
- Repository sync.
- PR sync.
- Review/comment/check ingestion.
- Polling/scheduled refresh.
- Queue ranking from real PR state.

Exit criteria:
- Team lead can see real open PRs across selected repositories.
- No write actions yet.

### Slice 3: Team Workspace Persistence

Goal: make team context durable and useful in ranking/filtering.

Deliverables:
- Team member CRUD.
- GitHub username and alias mapping.
- Ownership and expertise fields.
- Availability state.
- Filters and ranking signals that use team context.

Exit criteria:
- PRs map to team members reliably.
- Lead can edit what each person owns and works on.

### Slice 4: Agent Adapter Contract

Goal: introduce backend agent SDK abstraction.

Deliverables:
- `AgentAdapter` interface.
- Backend settings for opencode, Codex, Anthropic.
- Agent run records.
- Event stream shape.
- opencode adapter prototype.

Progress: the dashboard-facing contract now launches a local Node/TypeScript
runner instead of an HTTP opencode server. The runner protocol is stdin JSON in
and newline-delimited JSON events out, with opencode, Codex, and Claude behind
the same boundary. Runs are queued and executed asynchronously by the backend;
timestamped runner events are persisted and Actions polls while a run is active.
Active runs can be cancelled through the API and Actions; deterministic slow-run
coverage verifies streamed progress and process termination.

Exit criteria:
- Starting a run creates a durable run record.
- UI does not depend on a specific backend SDK.

### Slice 5: Approval-Gated Fix Flow

Goal: safely prepare and push remediations.

Deliverables:
- Prepare rebase/conflict/check-fix run.
- Generate patch summary.
- Run required checks.
- Approval screen.
- Push only after approval.
- Audit log.

Exit criteria:
- No backend can push without an approval record.
- Lead can inspect patch, checks, risk, and session log before approving.

Status: local implementation complete. Agent runs persist timestamped stage
events, isolated-workspace patch and diff material, configured check results,
risk summary, approval records, push outcomes, and Activity audit events. The
deterministic backend harness covers the approval gate and a successful push to
a local bare Git remote. A live GitHub push smoke test remains outstanding.

### Agent Run Sandboxing

Before expanding Agent Runs into a patch approval workspace, every run must
operate in an isolated workspace. The first local implementation uses a fresh
clone per run, detached at the captured base commit, under
`~/.mergeops/workspace/<run-id>/`. The configured checkout is used only as a
source and is never passed directly to an agent.

Phase 1 requirements:
- One independent workspace per run, including concurrent runs for one repo.
- Checkout from the GitHub PR ref when no local source checkout is configured.
- Capture and persist the base commit used by the run.
- Scrub the child-process environment and never provide push credentials.
- Enforce a wall-clock timeout and terminate the child process group on timeout.
- Keep push as a separate, approval-gated host action.

Later hardening:
- Rootless container per run.
- Network disabled by default with explicit package-registry allowlists.
- CPU, memory, process-count, and disk quotas.
- Workspace retention, cancellation, and cleanup policies.

### Slice 6: Bilingual Search

Goal: connect existing bilingual search skills to the cockpit.

Deliverables:
- Search adapter wrapper.
- English/Hebrew query support.
- Results panel for PRs, issues, comments, and code references.
- Repo/member scoped search.

Exit criteria:
- Search results can explain why a PR or issue is relevant in either language.

## Confirmed Stack

Use:
- React/Vite frontend
- Python/FastAPI backend
- Postgres for persistent data
- Redis-backed queue for sync and agent jobs
- GitHub OAuth or device login for contributor-friendly access
- Local-only first deployment

## First Build Target

Build a local developer version with:
- Vite frontend on localhost
- FastAPI backend on localhost
- typed fixtures before live GitHub
- local settings persistence
- backend adapter selection preserved from the prototype
- explicit repository path allowlist for later agent runs

Repository settings accept `owner/repo | /absolute/local/path` so agent runs can
be constrained to known local checkouts.

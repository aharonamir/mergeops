# MergeOps Roadmap

## Current State

`mergeops/` contains the original static prototype plus the first React/Vite and FastAPI local-only scaffold. It validates product shape, information architecture, core screens, theme behavior, team workspace fields, backend agent SDK selection, and fixture-backed API flow.

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

# MergeOps

<img width="1822" height="915" alt="image" src="https://github.com/user-attachments/assets/ca8bb079-9ede-40c4-801b-538722500b2e" />

MergeOps is a local-first cockpit for teams managing pull requests across
multiple repositories. It brings PR status, team context, bilingual search, and
supervised AI-assisted remediation into one workflow.

The original static prototype remains at `index.html`. The active application
is built from `frontend/` (React, TypeScript, Vite), `backend/` (FastAPI), and
`agent-runner/` (the local agent process boundary).

## Current status

The local application supports the core PR operations loop: sync GitHub PRs,
triage them in the cockpit, prepare an agent-assisted change in an isolated
workspace, inspect its diff and checks, then explicitly approve a push. It also
supports bilingual search for GitHub and GitCode PRs and issues.

This is a local developer build, not a hosted multi-user service. State is
persisted locally. The real GitHub push path has not had its live smoke test
yet; local approval-gate and push behavior is covered by the implementation's
deterministic harness.

## Main features

- **Cross-repository PR cockpit:** sync and triage GitHub pull requests with
  review state, checks, mergeability, branch freshness, comments, and owner
  context.
- **Team workspace:** maintain team profiles, GitHub identities, ownership,
  expertise, focus, timezone, and availability alongside PR operations.
- **PR inspection and remediation:** inspect PR details and review threads,
  prepare fixes or rebases, and see the generated diff, risk summary, and check
  results.
- **Human-controlled writes:** agent work happens in a per-run isolated
  workspace. A push is a separate action that requires explicit approval;
  agents do not receive push authority.
- **One runner for multiple agents:** select OpenCode, Codex, or Claude through
  the same local TypeScript runner boundary. Runs persist progress and audit
  events and can be cancelled.
- **Bilingual search:** search issues or pull requests in English or Simplified
  Chinese using GitHub or GitCode. Search runs in a temporary isolated,
  read-only workspace and uses the matching PR or issue search skill. Results
  have bilingual summaries and relevance explanations, normalized across
  agent output formats, and follow the UI language toggle.
- **Local preferences:** light, dark, and system themes, along with app settings,
  are available in the local cockpit.

## What is implemented and what remains

The implementation covers the local versions of the PR cockpit, team context,
agent-run lifecycle, approval-gated remediation, and bilingual search described
in the spec and roadmap. Some infrastructure described in the original spec is
still future work: hosted authentication, Postgres persistence, a Redis-backed
job queue, scheduled GitHub reconciliation, and deployment as a shared service.

Current boundaries:

- PR ingestion and write actions use GitHub. GitCode is currently supported as
  a bilingual search backend.
- GitHub sync uses a contributor token and imports PRs for registered team
  members.
- Persistence and run history are local to this installation.
- A live GitHub push smoke test remains outstanding.
- The original static prototype is kept for reference; it is not the active
  application.

## Run locally

Start both services together:

```bash
./start.sh
```

Stop both services and their reload processes:

```bash
./stop.sh
```

The app is normally available at `http://127.0.0.1:5170`; the API runs at
`http://127.0.0.1:8000`. Logs and PID files are kept in the ignored
`.mergeops-runtime/` directory.

To run the services separately:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

Build the local agent runner when runner code changes:

```bash
cd agent-runner
npm install
npm run build
```

FastAPI launches `agent-runner/dist/runner.js` as a child process. The runner
accepts one JSON payload on stdin and emits newline-delimited JSON events on
stdout.

## GitHub and repository setup

In Settings, configure a GitHub contributor token and repositories. Enter each
repository as `owner/repo`; to enable agent actions, add its local checkout
path:

```text
owner/repo | /absolute/local/path
```

Save the settings and run a sync. If GitHub returns an authentication or rate
limit error, MergeOps keeps the last known PR snapshot and records the sync
status.

Search has a separate service selector and read-only credentials for GitHub or
GitCode. Search jobs do not use the remediation push credential.

Local settings, edits, and run history are stored in
`backend/data/mergeops.local.json`; this file is ignored by git.

## Project docs

- [Implementation spec](docs/IMPLEMENTATION_SPEC.md)
- [Roadmap](docs/ROADMAP.md)
- [Presentation brief](docs/PRESENTATION_BRIEF.md)
- [Continue work notes](docs/CONTINUE.md)

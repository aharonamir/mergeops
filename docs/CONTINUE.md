# Continue MergeOps Work

Work from the repository folder:

```bash
cd /home/amir/workspace/mergeops
```

## Current State

- Local-only MergeOps app scaffold is in this repository.
- Frontend: React/Vite/TypeScript in `frontend/`.
- Backend: FastAPI/uv in `backend/`.
- Agent runner: TypeScript child-process boundary in `agent-runner/`.
- GitHub sync uses contributor-token mode and imports PRs for registered team
  members only.
- Agent runs are approval-gated and launched through the backend, not directly
  from the browser.
- OpenCode no longer requires a manually managed shared server. The runner uses
  the installed SDK V2 entry point to create and close a local OpenCode instance
  per job.

## Important Local Files

- `backend/data/mergeops.local.json`: local runtime data and credentials. This
  file is intentionally ignored by git.
- `backend/app/store.py`: local persistence, team CRUD, agent run orchestration.
- `backend/app/github_sync.py`: GitHub PR ingestion.
- `backend/app/adapters.py`: Python adapter that launches the TypeScript runner.
- `agent-runner/src/runner.ts`: TypeScript SDK runner for OpenCode, Codex, and
  Claude.
- `frontend/src/App.tsx`: dashboard UI and settings editor.

## Run Locally

Backend:

```bash
cd /home/amir/workspace/mergeops/backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd /home/amir/workspace/mergeops/frontend
npm install
npm run dev
```

Agent runner:

```bash
cd /home/amir/workspace/mergeops/agent-runner
npm install
npm run build
```

Open the Vite URL shown by the frontend command. It is normally
`http://127.0.0.1:5170/`; if that port is busy, Vite will choose another port.

## Current Verification Commands

Run from `/home/amir/workspace/mergeops`:

```bash
python3 -m py_compile backend/app/adapters.py backend/app/models.py backend/app/store.py backend/app/main.py backend/app/github_sync.py
npm --prefix frontend run build
npm --prefix agent-runner run build
git diff --check
```

## Repository Settings Format

In Settings, repositories can be entered as:

```text
owner/repo
owner/repo | /absolute/local/path
```

The local path is required before an agent action can run against that checkout.

## Next Required Fix

Fix review blocker `P2: Avoid selecting local paths by bare repo name`.

Problem:

- `PullRequest.repository` currently stores/display the short repo name.
- `LocalJsonStore._repository_config()` matches by either short name or
  `owner/name`.
- If two settings entries share the same repo name under different owners, an
  agent run can select the wrong local checkout.

Implementation target:

- Add an unambiguous repository field to PRs, such as `repositoryFullName` or
  `repositoryId`.
- Populate it in fixtures and in `github_sync.py`.
- Use that field in `store.create_agent_run()` when resolving local paths.
- Keep the UI display compatible with the short repo label.
- Add a regression test or deterministic harness proving that
  `owner-a/service | /tmp/a` and `owner-b/service | /tmp/b` resolve correctly.

## Near-Term Product Work After That

- Persist agent event logs instead of keeping only final run summary.
- Surface runner progress in the Agent Runs view.
- Add patch/diff review before approval.
- Add explicit approve-and-push action.
- Connect bilingual issue/PR search.
- Ingest checks/reviews more deeply from GitHub.

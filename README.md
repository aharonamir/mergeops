# MergeOps

Local-first PR-first SDLC cockpit.
<img width="1822" height="915" alt="image" src="https://github.com/user-attachments/assets/ca8bb079-9ede-40c4-801b-538722500b2e" />

The original static prototype is still available at `index.html`. The real app scaffold now lives in `frontend/` and `backend/`.

## Included

- Cross-repository PR intervention queue with synthetic PR data.
- Team workload strip and editable team member workspace.
- Settings for team, repositories, integrations, automation policy, search, and preferences.
- System/light/dark theme toggle with local persistence.
- PR inspection drawer with an approval-gated remediation flow.
- Configurable backend agent SDK selection: opencode, Codex, or Anthropic through a local TypeScript runner.

## Run The React/FastAPI App

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5170`.

Local edits and queued agent runs are stored in `backend/data/mergeops.local.json`.

The GitHub settings screen supports contributor-token mode. Add repositories as `owner/repo`, or `owner/repo | /absolute/local/path` when you want agent actions to run against a local checkout. Save, then run a sync. If GitHub returns an auth/rate-limit error, MergeOps keeps the last known PR snapshot and records the sync status.

Agent SDK runner:

```bash
cd agent-runner
npm install
npm run build
```

FastAPI invokes `agent-runner/dist/runner.js` as a local child process. The runner receives one JSON payload on stdin and returns newline-delimited JSON events on stdout.

## Product Boundary

The local app now has live GitHub PR sync and an approval-gated runner boundary. CI ingestion, bilingual search, patch review, and final push approval are still upcoming.

For the current handoff, setup commands, verification commands, and next
blocker, see `docs/CONTINUE.md`.

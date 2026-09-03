# MergeOps

Local-first PR-first SDLC cockpit.

The original static prototype is still available at `index.html`. The real app scaffold now lives in `frontend/` and `backend/`.

## Included

- Cross-repository PR intervention queue with synthetic PR data.
- Team workload strip and editable team member workspace.
- Settings for team, repositories, integrations, automation policy, search, and preferences.
- System/light/dark theme toggle with local persistence.
- PR inspection drawer with an approval-gated remediation flow.
- Configurable backend agent SDK selection: opencode, Codex, or Anthropic.

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

The GitHub settings screen supports contributor-token mode. Add repositories as `owner/repo`, save, then run a sync. If GitHub returns an auth/rate-limit error, MergeOps keeps the last known PR snapshot and records the sync status.

## Product Boundary

The prototype uses illustrative data only. Real GitHub, CI, bilingual search, and backend agent SDK integrations are intentionally not wired yet.

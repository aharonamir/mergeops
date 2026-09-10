# MergeOps Agent Guide

## Project overview

MergeOps is a local-first PR operations cockpit. The production app is split into:

- `frontend/`: React, TypeScript, and Vite UI.
- `backend/`: FastAPI service, local JSON persistence, GitHub sync, and action APIs.
- `agent-runner/`: TypeScript child-process boundary for OpenCode/Codex/Anthropic agent runs.
- `docs/`: implementation notes, roadmap, continuation notes, and wishlist.

The root `index.html`, `app.js`, and `styles.css` are the original static prototype. Prefer the `frontend/` and `backend/` app when implementing features.

## Development

Start the backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://127.0.0.1:5170`; the backend runs at `http://127.0.0.1:8000`.

Build the agent runner when changing runner code:

```bash
cd agent-runner
npm install
npm run build
```

## Verification

Run checks proportional to the change:

```bash
cd backend && uv run pytest
cd backend && python3 -m compileall app
cd frontend && npm run build
cd agent-runner && npm run check && npm run build
git diff --check
```

For UI changes, inspect the running app at desktop and mobile widths when layout is affected. Use Playwright for behavior or visual verification when available. Remove generated `.playwright-mcp/` artifacts before handoff.

## Frontend conventions

- Preserve the existing typography, spacing, color, and component tokens in `frontend/src/styles.css`.
- Keep data fetching and API behavior unchanged for presentation-only work.
- Put user-facing copy in `frontend/src/i18n.tsx`; use stable translation keys and provide both English (`en`) and Simplified Chinese (`zh`) strings. Do not concatenate translated fragments when a complete sentence key is clearer.
- Persist browser-only preferences through `localStorage` using a namespaced `mergeops.*` key.
- Keep controls keyboard accessible with visible focus states, useful labels, and responsive content that can expand for Chinese text.

## Backend and agent safety

- Keep local persistence behavior compatible with existing `backend/data/mergeops.local.json` data.
- Agent workspaces are isolated and approval-gated. Do not add push or merge capability to the agent workspace or bypass the approval boundary.
- The guarded Git executable may allow rebase and continuation but must continue to block and record merge/push attempts.
- Preserve rebase evidence, conflict snapshots, validation results, bounded transcript metadata, and failure events when extending agent runs.
- Treat GitHub sync and external writes as explicit operations. Do not infer permission to push, merge, delete, or modify remote state from a read-only request.

## Working-tree discipline

- Inspect `git status` before editing and preserve unrelated user changes.
- Use `apply_patch` for local edits.
- Do not reset, checkout, or otherwise discard user work.
- Do not commit unless the user explicitly asks for a commit.
- Keep generated build output and local runtime data out of commits unless the repository already tracks them.

## Handoff expectations

Report the files changed, checks run, any remaining warnings, and any intentionally preserved uncommitted changes. Keep unrelated wishlist or documentation edits separate from implementation commits.

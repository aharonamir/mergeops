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

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->

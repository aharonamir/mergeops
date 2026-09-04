# MergeOps Agent Runner

Local Node/TypeScript boundary for TypeScript-first coding agent SDKs.

FastAPI sends one JSON payload on stdin and reads newline-delimited JSON events from stdout. This keeps OpenCode, Codex, and Claude SDK dependencies out of the Python process while preserving the MergeOps approval gate.

## Build

```bash
npm install
npm run build
```

The backend runs `dist/runner.js`.

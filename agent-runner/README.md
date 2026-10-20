# MergeOps Agent Runner

Local Node/TypeScript boundary for coding agent processes.

FastAPI sends one JSON payload on stdin and reads newline-delimited JSON events from stdout. This keeps the OpenCode and Codex SDKs, and the Claude Code CLI, out of the Python process while preserving the MergeOps approval gate.

Claude Code support uses the installed `claude` CLI and the user's local authenticated profile. Direct PR reviews are available with Codex and Claude Code.

## Build

```bash
npm install
npm run build
```

The backend runs `dist/runner.js`.

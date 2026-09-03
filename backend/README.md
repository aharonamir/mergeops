# MergeOps Backend

Local-only FastAPI backend for the real MergeOps build.

## Run

```bash
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API exposes fixture-backed endpoints first:

- `GET /api/health`
- `GET /api/app-data`
- `POST /api/agent-runs`

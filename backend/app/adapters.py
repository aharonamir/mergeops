"""Backend-neutral agent adapter contract for local MergeOps runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Protocol


@dataclass(frozen=True)
class AgentRunRequest:
    pull_request_id: str
    repository: str
    pull_request_number: int
    action: str
    backend_id: str
    repository_local_path: str | None = None
    base_branch: str | None = None
    source_branch: str | None = None


@dataclass(frozen=True)
class AgentRunResult:
    status: str
    summary: str
    backend_session_id: str | None = None


class AgentAdapter(Protocol):
    """The dashboard-facing surface shared by every agent backend."""

    backend_id: str

    def create_run(self, request: AgentRunRequest) -> AgentRunResult:
        ...


class LocalAgentAdapter:
    """Safe local placeholder until a real SDK worker is connected."""

    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id

    def create_run(self, request: AgentRunRequest) -> AgentRunResult:
        return AgentRunResult(
            status="awaiting_approval",
            summary=(
                f"Queued {request.action.replace('_', ' ')} run via {self.backend_id}. "
                "No push will happen without approval."
            ),
        )


class SubprocessAgentAdapter:
    """Runs TypeScript-first agent SDKs behind a local Node process."""

    def __init__(self, backend_id: str, runner_path: Path) -> None:
        self.backend_id = backend_id
        self.runner_path = runner_path

    def create_run(self, request: AgentRunRequest) -> AgentRunResult:
        if not self.runner_path.exists():
            return AgentRunResult(
                status="failed",
                summary=(
                    "Agent runner is not built yet. Run `npm install` and `npm run build` "
                    "inside `agent-runner/`, then retry."
                ),
            )
        if request.repository_local_path is None:
            return AgentRunResult(
                status="failed",
                summary=(
                    f"No local path is configured for {request.repository}. "
                    "Add one in Settings as `owner/repo | /absolute/path`."
                ),
            )

        payload = {
            "backendId": request.backend_id,
            "repository": request.repository,
            "pullRequestId": request.pull_request_id,
            "pullRequestNumber": request.pull_request_number,
            "action": request.action,
            "repositoryLocalPath": request.repository_local_path,
            "baseBranch": request.base_branch,
            "sourceBranch": request.source_branch,
        }
        try:
            completed = subprocess.run(
                ["node", str(self.runner_path)],
                input=json.dumps(payload),
                capture_output=True,
                check=False,
                encoding="utf-8",
                timeout=90,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return AgentRunResult(status="failed", summary=f"Could not start agent runner: {exc}")

        result = self._parse_result(completed.stdout)
        if result is not None:
            return result
        message = completed.stderr.strip() or f"Agent runner exited with code {completed.returncode}"
        return AgentRunResult(status="failed", summary=message)

    def _parse_result(self, output: str) -> AgentRunResult | None:
        final_event: dict[str, object] | None = None
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "final":
                final_event = event
        if final_event is None:
            return None
        status = final_event.get("status")
        summary = final_event.get("summary")
        session_id = final_event.get("backendSessionId")
        if not isinstance(status, str) or not isinstance(summary, str):
            return None
        return AgentRunResult(
            status=status,
            summary=summary,
            backend_session_id=session_id if isinstance(session_id, str) else None,
        )


def adapter_registry(backends: list[tuple[str, str]]) -> dict[str, AgentAdapter]:
    """Build adapters from the enabled backend configuration."""
    project_root = Path(__file__).resolve().parents[2]
    runner_path = project_root / "agent-runner" / "dist" / "runner.js"
    registry: dict[str, AgentAdapter] = {}
    for backend_id, _endpoint in backends:
        registry[backend_id] = (
            SubprocessAgentAdapter(backend_id, runner_path)
            if backend_id in {"opencode", "codex", "anthropic"}
            else LocalAgentAdapter(backend_id)
        )
    return registry


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

"""Backend-neutral agent adapter contract for local MergeOps runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
from typing import Protocol


@dataclass(frozen=True)
class AgentRunRequest:
    run_id: str
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
    workspace_path: str | None = None
    base_commit: str | None = None


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

        try:
            workspace = RunWorkspace.create(request)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return AgentRunResult(status="failed", summary=f"Could not prepare isolated run workspace: {exc}")

        payload = {
            "backendId": request.backend_id,
            "repository": request.repository,
            "pullRequestId": request.pull_request_id,
            "pullRequestNumber": request.pull_request_number,
            "action": request.action,
            "repositoryLocalPath": str(workspace.path),
            "baseBranch": request.base_branch,
            "sourceBranch": request.source_branch,
        }
        try:
            environment = {
                key: os.environ[key]
                for key in ("PATH", "LANG", "LC_ALL", "TMPDIR")
                if key in os.environ
            }
            environment.update({
                "HOME": str(workspace.path),
                "MERGEOPS_RUN_ID": request.run_id,
                "MERGEOPS_NO_PUSH": "1",
            })
            process = subprocess.Popen(
                ["node", str(self.runner_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                cwd=workspace.path,
                env=environment,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(input=json.dumps(payload), timeout=90)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
                return AgentRunResult(
                    status="failed",
                    summary="Agent runner timed out after 90 seconds; its process group was terminated.",
                    workspace_path=str(workspace.path),
                    base_commit=workspace.base_commit,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            return AgentRunResult(status="failed", summary=f"Could not start agent runner: {exc}")

        result = self._parse_result(stdout)
        if result is not None:
            return result.__class__(
                status=result.status,
                summary=result.summary,
                backend_session_id=result.backend_session_id,
                workspace_path=str(workspace.path),
                base_commit=workspace.base_commit,
            )
        message = stderr.strip() or f"Agent runner exited with code {process.returncode}"
        return AgentRunResult(
            status="failed",
            summary=message,
            workspace_path=str(workspace.path),
            base_commit=workspace.base_commit,
        )

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


class RunWorkspace:
    """Creates an independent, detached clone for one agent run."""

    root = Path(__file__).resolve().parents[1] / "data" / "agent-runs"

    def __init__(self, path: Path, base_commit: str) -> None:
        self.path = path
        self.base_commit = base_commit

    @classmethod
    def create(cls, request: AgentRunRequest) -> "RunWorkspace":
        source = Path(request.repository_local_path or "").expanduser().resolve()
        if not source.is_dir():
            raise RuntimeError(f"Configured repository path does not exist: {source}")
        source_root = cls._git(source, "rev-parse", "--show-toplevel").strip()
        if Path(source_root).resolve() != source:
            raise RuntimeError(f"Configured path is not the repository root: {source}")

        run_root = cls.root / request.run_id
        checkout = run_root / "checkout"
        if run_root.exists():
            raise RuntimeError(f"Run workspace already exists: {run_root}")
        run_root.mkdir(parents=True, exist_ok=False)
        try:
            cls._git(run_root, "clone", "--no-local", "--no-checkout", str(source), str(checkout))
            branch = request.source_branch or request.base_branch
            if branch and cls._git_optional(checkout, "rev-parse", "--verify", f"refs/heads/{branch}"):
                cls._git(checkout, "checkout", "--detach", branch)
            else:
                cls._git(checkout, "checkout", "--detach", "HEAD")
            base_commit = cls._git(checkout, "rev-parse", "HEAD").strip()
        except Exception:
            # Preserve the run directory for diagnosis, but never expose a partial checkout.
            raise
        return cls(checkout, base_commit)

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=30
        )
        return result.stdout

    @staticmethod
    def _git_optional(cwd: Path, *args: str) -> bool:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=30
        )
        return result.returncode == 0


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

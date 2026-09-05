"""Backend-neutral agent adapter contract for local MergeOps runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import base64
import os
from pathlib import Path
import signal
import shlex
import shutil
import subprocess
import threading
import time
from queue import Empty, Queue
from typing import Callable, Protocol


@dataclass(frozen=True)
class AgentRunRequest:
    run_id: str
    pull_request_id: str
    repository: str
    pull_request_number: int
    action: str
    backend_id: str
    repository_local_path: str | None = None
    repository_remote_url: str | None = None
    repository_token: str | None = None
    pull_request_ref: str | None = None
    base_branch: str | None = None
    source_branch: str | None = None


@dataclass(frozen=True)
class AgentRunResult:
    status: str
    summary: str
    backend_session_id: str | None = None
    workspace_path: str | None = None
    base_commit: str | None = None
    events: list[dict[str, object]] | None = None


class AgentAdapter(Protocol):
    """The dashboard-facing surface shared by every agent backend."""

    backend_id: str

    def create_run(self, request: AgentRunRequest, on_event: Callable[[dict[str, object]], None] | None = None, cancel_event: threading.Event | None = None) -> AgentRunResult:
        ...


class LocalAgentAdapter:
    """Safe local placeholder until a real SDK worker is connected."""

    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id

    def create_run(self, request: AgentRunRequest, on_event: Callable[[dict[str, object]], None] | None = None, cancel_event: threading.Event | None = None) -> AgentRunResult:
        if cancel_event and cancel_event.is_set():
            result = AgentRunResult(status="cancelled", summary="Agent run cancelled before the worker started.", events=[self._event("cancelled", "Agent run cancelled before the worker started.")])
            if on_event:
                on_event(result.events[0])
            return result
        result = AgentRunResult(
            status="awaiting_approval",
            summary=(
                f"Queued {request.action.replace('_', ' ')} run via {self.backend_id}. "
                "No push will happen without approval."
            ),
        )
        if on_event:
            on_event({"type": "final", "message": result.summary, "createdAt": utc_now()})
        return result


class SubprocessAgentAdapter:
    """Runs TypeScript-first agent SDKs behind a local Node process."""

    def __init__(self, backend_id: str, runner_path: Path) -> None:
        self.backend_id = backend_id
        self.runner_path = runner_path

    def create_run(self, request: AgentRunRequest, on_event: Callable[[dict[str, object]], None] | None = None, cancel_event: threading.Event | None = None) -> AgentRunResult:
        if cancel_event and cancel_event.is_set():
            result = AgentRunResult(status="cancelled", summary="Agent run cancelled before workspace creation.", events=[self._event("cancelled", "Agent run cancelled before workspace creation.")])
            if on_event:
                on_event(result.events[0])
            return result
        if not self.runner_path.exists():
            result = AgentRunResult(
                status="failed",
                summary=(
                    "Agent runner is not built yet. Run `npm install` and `npm run build` "
                    "inside `agent-runner/`, then retry."
                ),
                events=[self._event("error", "Agent runner is not built yet.")],
            )
            if on_event:
                on_event(result.events[0])
            return result
        if request.repository_local_path is None and request.repository_remote_url is None:
            result = AgentRunResult(
                status="failed",
                summary=(
                    f"No local path is configured for {request.repository}. "
                    "Add one in Settings as `owner/repo | /absolute/path`."
                ),
                events=[self._event("error", f"No local path or remote repository is configured for {request.repository}.")],
            )
            if on_event:
                on_event(result.events[0])
            return result

        try:
            workspace = RunWorkspace.create(request)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            result = AgentRunResult(
                status="failed",
                summary=f"Could not prepare isolated run workspace: {exc}",
                events=[self._event("error", f"Could not prepare isolated run workspace: {exc}")],
            )
            if on_event:
                on_event(result.events[0])
            return result

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
            assert process.stdin is not None
            process.stdin.write(json.dumps(payload))
            process.stdin.close()
            output_queue: Queue[tuple[str, str | None]] = Queue()

            def drain(stream: object, stream_name: str) -> None:
                for line in stream:  # type: ignore[union-attr]
                    output_queue.put((stream_name, line))
                output_queue.put((stream_name, None))

            stdout_thread = threading.Thread(target=drain, args=(process.stdout, "stdout"), daemon=True)
            stderr_thread = threading.Thread(target=drain, args=(process.stderr, "stderr"), daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            streams_closed = 0
            deadline = time.monotonic() + 90
            while streams_closed < 2:
                if cancel_event and cancel_event.is_set() and process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                    result = AgentRunResult(
                        status="cancelled",
                        summary="Agent run cancelled; its process group was terminated.",
                        workspace_path=str(workspace.path),
                        base_commit=workspace.base_commit,
                        events=[self._event("cancelled", "Agent run cancelled; its process group was terminated.")],
                    )
                    if on_event:
                        on_event(result.events[0])
                    return result
                if time.monotonic() > deadline and process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                    result = AgentRunResult(
                        status="failed",
                        summary="Agent runner timed out after 90 seconds; its process group was terminated.",
                        workspace_path=str(workspace.path),
                        base_commit=workspace.base_commit,
                        events=[self._event("error", "Agent runner timed out after 90 seconds; its process group was terminated.")],
                    )
                    if on_event:
                        on_event(result.events[0])
                    return result
                try:
                    stream_name, line = output_queue.get(timeout=0.1)
                except Empty:
                    continue
                if line is None:
                    streams_closed += 1
                    continue
                if stream_name == "stdout":
                    stdout_lines.append(line)
                    event = self._parse_event_line(line)
                    if event:
                        if on_event:
                            on_event(event)
                else:
                    stderr_lines.append(line)
            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            if process.poll() is None:
                process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            result = AgentRunResult(status="failed", summary=f"Could not start agent runner: {exc}", events=[self._event("error", f"Could not start agent runner: {exc}")])
            if on_event:
                on_event(result.events[0])
            return result

        result, events = self._parse_result(stdout)
        if result is not None:
            return result.__class__(
                status=result.status,
                summary=result.summary,
                backend_session_id=result.backend_session_id,
                workspace_path=str(workspace.path),
                base_commit=workspace.base_commit,
                events=events,
            )
        message = stderr.strip() or f"Agent runner exited with code {process.returncode}"
        if stderr.strip():
            stderr_event = self._event("stderr", stderr.strip())
            events.append(stderr_event)
            if on_event:
                on_event(stderr_event)
        error_event = self._event("error", message)
        events.append(error_event)
        if on_event:
            on_event(error_event)
        return AgentRunResult(
            status="failed",
            summary=message,
            workspace_path=str(workspace.path),
            base_commit=workspace.base_commit,
            events=events,
        )

    @staticmethod
    def _parse_event_line(line: str) -> dict[str, object] | None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            return None
        message = event.get("message") or event.get("summary")
        if not isinstance(message, str):
            return None
        return {"type": event["type"], "message": message, "createdAt": event.get("createdAt") if isinstance(event.get("createdAt"), str) else utc_now()}

    @staticmethod
    def _event(event_type: str, message: str) -> dict[str, object]:
        return {"type": event_type, "message": message, "createdAt": utc_now()}

    def _parse_result(self, output: str) -> tuple[AgentRunResult | None, list[dict[str, object]]]:
        final_event: dict[str, object] | None = None
        events: list[dict[str, object]] = []
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                continue
            message = event.get("message") or event.get("summary")
            if isinstance(message, str):
                events.append({
                    "type": event["type"],
                    "message": message,
                    "createdAt": event.get("createdAt") if isinstance(event.get("createdAt"), str) else utc_now(),
                })
            if event.get("type") == "final":
                final_event = event
        if final_event is None:
            return None, events
        status = final_event.get("status")
        summary = final_event.get("summary")
        session_id = final_event.get("backendSessionId")
        if not isinstance(status, str) or not isinstance(summary, str):
            return None, events
        return AgentRunResult(
            status=status,
            summary=summary,
            backend_session_id=session_id if isinstance(session_id, str) else None,
        ), events


class RunWorkspace:
    """Creates an independent, detached clone for one agent run."""

    root = Path("~/.mergeops/workspace").expanduser()

    def __init__(self, path: Path, base_commit: str) -> None:
        self.path = path
        self.base_commit = base_commit

    @classmethod
    def create(cls, request: AgentRunRequest) -> "RunWorkspace":
        source = Path(request.repository_local_path or "").expanduser().resolve() if request.repository_local_path else None
        if source is not None:
            if not source.is_dir():
                raise RuntimeError(f"Configured repository path does not exist: {source}")
            source_root = cls._git(source, "rev-parse", "--show-toplevel").strip()
            if Path(source_root).resolve() != source:
                raise RuntimeError(f"Configured path is not the repository root: {source}")
        elif request.repository_remote_url is None:
            raise RuntimeError("No local checkout or remote repository is configured")

        run_root = cls.root / request.run_id
        checkout = run_root / "checkout"
        if run_root.exists():
            raise RuntimeError(f"Run workspace already exists: {run_root}")
        cls.root.mkdir(parents=True, exist_ok=True)
        run_root.mkdir(parents=True, exist_ok=False)
        try:
            clone_args = ["clone", "--no-checkout"]
            if source is not None:
                clone_args.insert(1, "--no-local")
            cls._git(run_root, *clone_args, str(source) if source is not None else request.repository_remote_url or "", str(checkout), token=request.repository_token)
            branch = request.source_branch or request.base_branch
            if request.pull_request_ref:
                pr_branch = f"mergeops-pr-{request.pull_request_number}"
                cls._git(checkout, "fetch", "origin", f"+{request.pull_request_ref}:refs/heads/{pr_branch}", token=request.repository_token)
                cls._git(checkout, "checkout", "--detach", pr_branch)
            elif branch and cls._git_optional(checkout, "rev-parse", "--verify", f"refs/heads/{branch}"):
                cls._git(checkout, "checkout", "--detach", branch)
            else:
                cls._git(checkout, "checkout", "--detach", "HEAD")
            base_commit = cls._git(checkout, "rev-parse", "HEAD").strip()
        except Exception:
            cls.cleanup(request.run_id)
            raise
        return cls(checkout, base_commit)

    @classmethod
    def cleanup(cls, run_id: str) -> None:
        run_root = (cls.root / run_id).resolve()
        root = cls.root.resolve()
        if root not in run_root.parents:
            raise ValueError("Run workspace is outside the MergeOps workspace root")
        if run_root.exists():
            shutil.rmtree(run_root)

    @staticmethod
    def _git(cwd: Path, *args: str, token: str | None = None) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=120,
            env=RunWorkspace._git_environment(token),
        )
        return result.stdout

    @staticmethod
    def _git_optional(cwd: Path, *args: str, token: str | None = None) -> bool:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=120,
            env=RunWorkspace._git_environment(token),
        )
        return result.returncode == 0

    @staticmethod
    def _git_environment(token: str | None) -> dict[str, str]:
        environment = os.environ.copy()
        if token:
            credentials = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            environment.update({
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {credentials}",
            })
        return environment


def inspect_workspace(path: Path, required_checks: list[str] | None = None) -> tuple[str, str, list[dict[str, object]], str]:
    """Capture the review material produced in an isolated workspace."""
    started = utc_now()
    stat = subprocess.run(["git", "diff", "--stat"], cwd=path, capture_output=True, text=True, check=False, timeout=30)
    diff = subprocess.run(["git", "diff", "--no-ext-diff", "--unified=3"], cwd=path, capture_output=True, text=True, check=False, timeout=30)
    summary = stat.stdout.strip() or "No working-tree patch was produced."
    checks = []
    for command in required_checks or ["git diff --check"]:
        check_started = utc_now()
        args = ["git", "diff", "--check"] if command == "git diff --check" else shlex.split(command)
        try:
            result = subprocess.run(args, cwd=path, capture_output=True, text=True, check=False, timeout=120)
            status = "passed" if result.returncode == 0 else "failed"
            output = (result.stdout + result.stderr).strip()[:20_000]
            check_summary = "Check passed." if result.returncode == 0 else f"Check exited with code {result.returncode}."
        except (OSError, subprocess.SubprocessError) as exc:
            status = "failed"
            output = str(exc)
            check_summary = f"Check could not complete: {exc}"
        check_finished = utc_now()
        checks.append({
            "name": command,
            "status": status,
            "summary": check_summary,
            "output": output,
            "startedAt": check_started,
            "finishedAt": check_finished,
        })
    failed = sum(check["status"] == "failed" for check in checks)
    risk = "High risk: one or more required checks failed." if failed else ("Medium risk: patch requires human review." if diff.stdout.strip() else "Low risk: no working-tree patch detected.")
    return summary, diff.stdout[:100_000], checks, risk


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

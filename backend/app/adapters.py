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
    existing_workspace_path: str | None = None
    repository_token: str | None = None
    pull_request_ref: str | None = None
    base_branch: str | None = None
    source_branch: str | None = None
    review_diff: str | None = None
    previous_agent_output: str | None = None
    runner_timeout_seconds: int = 600


@dataclass(frozen=True)
class AgentRunResult:
    status: str
    summary: str
    output: str | None = None
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
        if request.existing_workspace_path is None and request.repository_local_path is None and request.repository_remote_url is None:
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

        if request.existing_workspace_path:
            try:
                workspace = RunWorkspace.from_existing(request.existing_workspace_path)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                result = AgentRunResult(
                    status="failed",
                    summary=f"Could not reuse isolated run workspace: {exc}",
                    events=[self._event("error", f"Could not reuse isolated run workspace: {exc}")],
                )
                if on_event:
                    on_event(result.events[0])
                return result
        else:
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

        if request.action in {"fix_conflicts", "rebase"}:
            try:
                rebase_state = RunWorkspace.prepare_rebase(workspace, request.base_branch)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                event = self._event("error", f"Could not prepare required rebase: {exc}")
                result = AgentRunResult(
                    status="failed",
                    summary=f"Could not prepare required rebase: {exc}",
                    workspace_path=str(workspace.path),
                    base_commit=workspace.base_commit,
                    events=[event],
                )
                if on_event:
                    on_event(event)
                return result
            if on_event:
                on_event(self._event(
                    "rebase_conflicts" if rebase_state else "rebase_prepared",
                    "Rebase started with conflicts; waiting for the agent to resolve them."
                    if rebase_state
                    else "Workspace rebased onto the base branch before the agent started.",
                ))
            conflict_files = RunWorkspace.unmerged_files(workspace)
        else:
            conflict_files = []

        opencode_profile_files = self._prepare_opencode_profile(workspace.path)
        review_baseline = self._workspace_fingerprint(workspace.path) if request.action == "review_patch" else None
        git_guard = self._prepare_git_guard(workspace.path.parent)
        payload = {
            "backendId": request.backend_id,
            "repository": request.repository,
            "pullRequestId": request.pull_request_id,
            "pullRequestNumber": request.pull_request_number,
            "action": request.action,
            "repositoryLocalPath": str(workspace.path),
            "baseBranch": request.base_branch,
            "sourceBranch": request.source_branch,
            "runnerTimeoutSeconds": request.runner_timeout_seconds,
            "conflictFiles": conflict_files,
            "reviewDiff": request.review_diff,
            "previousAgentOutput": request.previous_agent_output,
        }
        try:
            inherited_path = os.environ.get("PATH", "")
            opencode_bin = Path.home() / ".opencode" / "bin"
            path_entries = [str(git_guard.parent), str(opencode_bin), inherited_path] if opencode_bin.is_dir() else [str(git_guard.parent), inherited_path]
            environment = {
                key: os.environ[key]
                for key in ("PATH", "LANG", "LC_ALL", "TMPDIR")
                if key in os.environ
            }
            environment["PATH"] = os.pathsep.join(entry for entry in path_entries if entry)
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
            deadline = time.monotonic() + request.runner_timeout_seconds
            while streams_closed < 2:
                if request.action in {"fix_conflicts", "rebase"} and RunWorkspace.merge_in_progress(workspace):
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=5)
                    message = "Agent attempted git merge; conflict fixes must use rebase."
                    result = AgentRunResult(
                        status="failed",
                        summary=message,
                        workspace_path=str(workspace.path),
                        base_commit=workspace.base_commit,
                        events=[self._event("error", message)],
                    )
                    if on_event:
                        on_event(result.events[0])
                    return result
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
                        summary=f"Agent runner timed out after {request.runner_timeout_seconds} seconds; its process group was terminated.",
                        workspace_path=str(workspace.path),
                        base_commit=workspace.base_commit,
                        events=[self._event("error", f"Agent runner timed out after {request.runner_timeout_seconds} seconds; its process group was terminated.")],
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
        finally:
            self._cleanup_opencode_profile(opencode_profile_files)

        if review_baseline is not None and self._workspace_fingerprint(workspace.path) != review_baseline:
            event = self._event("error", "Patch review changed the workspace; review-only runs must leave files untouched.")
            if on_event:
                on_event(event)
            return AgentRunResult(
                status="failed",
                summary="Patch review changed the workspace; review-only runs must leave files untouched.",
                workspace_path=str(workspace.path),
                base_commit=workspace.base_commit,
                events=[event],
            )

        result, events = self._parse_result(stdout)
        if result is not None:
            return result.__class__(
                status=result.status,
                summary=result.summary,
                backend_session_id=result.backend_session_id,
                output=result.output,
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

    @staticmethod
    def _prepare_opencode_profile(workspace: Path) -> list[Path]:
        """Stage only OpenCode's config/auth files inside the isolated HOME."""
        (workspace / ".local" / "share" / "opencode" / "log").mkdir(parents=True, exist_ok=True)
        user_home = Path.home()
        mappings = [
            (user_home / ".local" / "share" / "opencode" / "auth.json", workspace / ".local" / "share" / "opencode" / "auth.json"),
            (user_home / ".config" / "opencode" / "opencode.json", workspace / ".config" / "opencode" / "opencode.json"),
            (user_home / ".config" / "opencode" / "opencode.jsonc", workspace / ".config" / "opencode" / "opencode.jsonc"),
            (user_home / ".opencode" / "opencode.json", workspace / ".opencode" / "opencode.json"),
            (user_home / ".opencode" / "opencode.jsonc", workspace / ".opencode" / "opencode.jsonc"),
        ]
        copied: list[Path] = []
        for source, destination in mappings:
            if source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied.append(destination)
        return copied

    @staticmethod
    def _cleanup_opencode_profile(files: list[Path]) -> None:
        for path in files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _prepare_git_guard(run_root: Path) -> Path:
        """Reject merge commands inside agent runs; conflict fixes must use rebase."""
        git_path = shutil.which("git")
        if git_path is None:
            raise RuntimeError("git is not available for the agent run")
        guard_dir = run_root / ".mergeops-bin"
        guard_dir.mkdir(parents=True, exist_ok=True)
        guard = guard_dir / "git"
        guard.write_text(
            "#!/bin/sh\n"
            "command=''\n"
            "skip_next=0\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$skip_next\" = 1 ]; then skip_next=0; continue; fi\n"
            "  case \"$arg\" in\n"
            "    -C|-c|--git-dir|--work-tree) skip_next=1 ;;\n"
            "    -*) ;;\n"
            "    *) command=\"$arg\"; break ;;\n"
            "  esac\n"
            "done\n"
            "if [ \"$command\" = \"merge\" ]; then\n"
            "  echo 'MergeOps guard: git merge is disabled; use git rebase for conflict fixes.' >&2\n"
            "  exit 64\n"
            "fi\n"
            f"exec {shlex.quote(git_path)} \"$@\"\n",
            encoding="utf-8",
        )
        guard.chmod(0o755)
        return guard

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
        output = final_event.get("output")
        if not isinstance(status, str) or not isinstance(summary, str):
            return None, events
        return AgentRunResult(
            status=status,
            summary=summary,
            output=output if isinstance(output, str) else None,
            backend_session_id=session_id if isinstance(session_id, str) else None,
        ), events

    @staticmethod
    def _workspace_fingerprint(path: Path) -> tuple[str, str, str, str]:
        pathspec = ["--", ".", ":(exclude).local", ":(exclude).config/opencode", ":(exclude).opencode"]
        status = subprocess.run(["git", "status", "--porcelain=v1", *pathspec], cwd=path, capture_output=True, text=True, check=False, timeout=30)
        diff = subprocess.run(["git", "diff", "--no-ext-diff", *pathspec], cwd=path, capture_output=True, text=True, check=False, timeout=30)
        cached = subprocess.run(["git", "diff", "--cached", "--no-ext-diff", *pathspec], cwd=path, capture_output=True, text=True, check=False, timeout=30)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=False, timeout=30)
        return status.stdout, diff.stdout, cached.stdout, head.stdout


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
            elif branch and cls._git_optional(checkout, "rev-parse", "--verify", f"refs/remotes/origin/{branch}"):
                cls._git(checkout, "checkout", "--detach", f"origin/{branch}")
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

    @classmethod
    def from_existing(cls, workspace_path: str) -> "RunWorkspace":
        workspace = Path(workspace_path).expanduser().resolve()
        root = cls.root.resolve()
        if root not in workspace.parents:
            raise RuntimeError("Existing workspace is outside the MergeOps workspace root")
        if not workspace.is_dir():
            raise RuntimeError(f"Existing workspace does not exist: {workspace}")
        source_root = cls._git(workspace, "rev-parse", "--show-toplevel").strip()
        if Path(source_root).resolve() != workspace:
            raise RuntimeError(f"Existing workspace is not a repository root: {workspace}")
        base_commit = cls._git(workspace, "rev-parse", "HEAD").strip()
        return cls(workspace, base_commit)

    @classmethod
    def prepare_rebase(cls, workspace: "RunWorkspace", base_branch: str | None) -> bool:
        """Start the required rebase, returning whether it stopped on conflicts."""
        if not base_branch:
            raise RuntimeError("the pull request has no base branch")
        base_ref = cls._resolve_base_ref(workspace.path, base_branch)
        cls._git(workspace.path, "config", "user.name", "MergeOps Agent")
        cls._git(workspace.path, "config", "user.email", "mergeops-agent@localhost")
        result = subprocess.run(
            ["git", "rebase", base_ref],
            cwd=workspace.path,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env=cls._git_environment(None),
        )
        if result.returncode == 0:
            return False
        if (workspace.path / ".git" / "rebase-merge").exists() or (workspace.path / ".git" / "rebase-apply").exists():
            return True
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git rebase {base_ref} failed: {detail or f'exited with code {result.returncode}'}")

    @staticmethod
    def merge_in_progress(workspace: "RunWorkspace") -> bool:
        """Detect a merge state without confusing it with Git's rebase state."""
        return (workspace.path / ".git" / "MERGE_HEAD").is_file()

    @staticmethod
    def unmerged_files(workspace: "RunWorkspace") -> list[str]:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=workspace.path,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return [line for line in result.stdout.splitlines() if line]

    @staticmethod
    def _resolve_base_ref(checkout: Path, base_branch: str) -> str:
        candidates = [f"refs/remotes/origin/{base_branch}", f"refs/heads/{base_branch}", base_branch]
        for candidate in candidates:
            if RunWorkspace._git_optional(checkout, "rev-parse", "--verify", candidate):
                return candidate.removeprefix("refs/remotes/").removeprefix("refs/heads/") if candidate.startswith("refs/") else candidate
        raise RuntimeError(f"base branch does not exist in the isolated repository: {base_branch}")

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


def inspect_workspace(path: Path, required_checks: list[str] | None = None, committed_base: str | None = None) -> tuple[str, str, list[dict[str, object]], str]:
    """Capture the review material produced in an isolated workspace."""
    stat = subprocess.run(["git", "diff", "--stat"], cwd=path, capture_output=True, text=True, check=False, timeout=30)
    diff = subprocess.run(["git", "diff", "--no-ext-diff", "--unified=3"], cwd=path, capture_output=True, text=True, check=False, timeout=30)
    if not diff.stdout.strip() and committed_base:
        stat = subprocess.run(["git", "diff", "--stat", committed_base], cwd=path, capture_output=True, text=True, check=False, timeout=30)
        diff = subprocess.run(["git", "diff", "--no-ext-diff", "--unified=3", committed_base], cwd=path, capture_output=True, text=True, check=False, timeout=30)
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

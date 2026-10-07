from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, Thread
from uuid import uuid4
from urllib.parse import urlparse

from pydantic import Field

from .adapters import AgentRunRequest, AgentRunResult, RunWorkspace, SubprocessAgentAdapter, adapter_registry, inspect_workspace, utc_now
from .fixtures import agent_backends, agent_runs, github_settings, pull_requests, team_members
from .ledger import ExecutionLedger
from .models import ActionRecord, ActionSummary, ActivityEvent, AgentFeedback, AgentRun, AgentRunEvent, AgentRunSummary, AgentSettings, AppData, ApprovalRecord, BoundedText, CheckResult, CheckoutResult, CreatePrNoteRequest, CreateRevisionRequest, CreateTeamMemberRequest, GitHubSettings, GitHubSettingsPublic, PostReviewRepliesRequest, PrAnnotations, PrNote, PullRequest, RebaseEvidence, ReplyDraft, ReplyResult, RepositoryConfig, ReviewThread, ReviewThreadComment, ReviewThreadSnapshot, ReviewDisposition, SearchResult, SearchRun, SearchRunRequest, SearchSettings, SearchSettingsPublic, TeamMember, UpdateAgentSettingsRequest, UpdateGitHubSettingsRequest, UpdatePrNoteRequest, UpdateSearchSettingsRequest, UpdateTeamMemberRequest


class PersistedAppData(AppData):
    agentRuns: list[AgentRun]
    actions: list[ActionRecord] = Field(default_factory=list)
    githubPrivate: GitHubSettings
    prAnnotations: list[PrAnnotations] = Field(default_factory=list)
    reviewThreadSnapshots: list[ReviewThreadSnapshot] = Field(default_factory=list)
    searchSettingsPrivate: SearchSettings = Field(default_factory=SearchSettings)


class LocalJsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._write_lock = Lock()
        self._cancel_events: dict[str, Event] = {}
        self.ledger = ExecutionLedger(path.with_suffix(".sqlite3"))
        self._worker_stop = Event()
        self._worker_thread: Thread | None = None
        self._worker_executor: ThreadPoolExecutor | None = None
        self._worker_owner = self.ledger.owner()
        self._recover_execution_state()

    def start_worker(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_stop.clear()
        self._worker_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mergeops-agent")
        self._worker_thread = Thread(target=self._worker_loop, name="mergeops-execution-worker", daemon=True)
        self._worker_thread.start()

    def stop_worker(self) -> None:
        self._worker_stop.set()
        for job in self.ledger.active_jobs():
            process_group = job.get("process_group")
            if process_group:
                try:
                    os.killpg(int(process_group), 15)
                except (OSError, ProcessLookupError):
                    pass
        if self._worker_executor:
            self._worker_executor.shutdown(wait=False, cancel_futures=False)

    def _worker_loop(self) -> None:
        futures = set()
        while not self._worker_stop.wait(0.15):
            futures = {future for future in futures if not future.done()}
            if len(futures) >= 4 or self._worker_executor is None:
                continue
            job = self.ledger.claim(self._worker_owner)
            if job is None:
                continue
            future = self._worker_executor.submit(self._execute_claimed_job, job)
            futures.add(future)

    def _execute_claimed_job(self, job: dict[str, object]) -> None:
        run_id = str(job["id"])
        payload = job["payload"]
        if not isinstance(payload, dict):
            self.ledger.finish(run_id, "failed")
            return
        lease_stop = Event()
        def renew() -> None:
            while not lease_stop.wait(10):
                self.ledger.heartbeat(run_id, self._worker_owner)
        lease_thread = Thread(target=renew, name=f"mergeops-lease-{run_id}", daemon=True)
        lease_thread.start()
        try:
            if payload.get("jobType") == "search":
                self.execute_search_run(run_id)
            elif payload.get("action") == "review_patch":
                self.execute_patch_review(run_id, str(payload["backendId"]), str(payload["parentRunId"]))
            else:
                self.execute_agent_run(run_id, str(payload["backendId"]), str(payload["pullRequestId"]), str(payload["action"]))
        finally:
            lease_stop.set()
            self.ledger.finish(run_id, "cancelled" if self.ledger.is_cancel_requested(run_id) else "finished")

    def _recover_execution_state(self) -> None:
        """Make orphaned in-flight work visible before accepting new work."""
        if not self.path.exists():
            return
        data = self._load()
        changed = False
        ledger_jobs = {str(job["id"]): job for job in self.ledger.active_jobs()}
        for run in data.agentRuns:
            if run.status not in {"running", "checks_running"}:
                if run.status == "queued":
                    self.ledger.ensure_queued(run.id, self._job_payload(run), run.createdAt)
                continue
            job = ledger_jobs.get(run.id)
            process_pid = int(job["process_pid"]) if job and job.get("process_pid") else None
            safe_identity = False
            if process_pid:
                try:
                    command_line = Path(f"/proc/{process_pid}/cmdline").read_bytes().decode(errors="ignore")
                    environment = Path(f"/proc/{process_pid}/environ").read_bytes()
                    run_marker = f"MERGEOPS_RUN_ID={run.id}".encode()
                    safe_identity = "agent-runner" in command_line and run_marker in environment
                except OSError:
                    safe_identity = False
                if safe_identity:
                    try:
                        os.killpg(int(job.get("process_group") or process_pid), 15)
                    except ProcessLookupError:
                        # The verified process exited between inspection and
                        # termination, which is already a safe outcome.
                        pass
                    except OSError:
                        safe_identity = False
            # Without a verified runner identity we cannot know whether the
            # recorded PID is still this run, so leave the run behind an
            # explicit human recovery gate instead of making it retryable.
            next_status = "interrupted" if safe_identity else "recovery_required"
            replacement = run.model_copy(update={
                "status": next_status,
                "summary": "The backend restarted while this run was active. Inspect the retained workspace before retrying.",
                "recoveryNote": "The recorded runner was terminated during recovery." if safe_identity else "Automatic resume is disabled; the previous runner identity could not be safely verified. Confirm that no old runner remains before retrying.",
                "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type=next_status, message="Backend restart interrupted the run; automatic resume is disabled.", createdAt=utc_now())],
            })
            data.agentRuns = [replacement if item.id == run.id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": replacement.status, "summary": replacement.summary, "events": replacement.events, "recoveryNote": replacement.recoveryNote}) if item.id == run.id else item for item in data.actions]
            self.ledger.finish(run.id, "interrupted")
            changed = True
        for run in data.searchRuns:
            if run.status == "queued":
                self.ledger.ensure_queued(run.id, {"jobType": "search"}, run.createdAt)
            elif run.status == "running":
                job = ledger_jobs.get(run.id)
                process_pid = int(job["process_pid"]) if job and job.get("process_pid") else None
                verified = False
                if process_pid:
                    try:
                        command_line = Path(f"/proc/{process_pid}/cmdline").read_bytes().decode(errors="ignore")
                        environment = Path(f"/proc/{process_pid}/environ").read_bytes()
                        verified = "agent-runner" in command_line and f"MERGEOPS_RUN_ID={run.id}".encode() in environment
                    except OSError:
                        verified = False
                if verified and job:
                    try:
                        os.killpg(int(job.get("process_group") or process_pid), 15)
                    except OSError:
                        pass
                interrupted = run.model_copy(update={"status": "interrupted", "summary": "The backend restarted during this search. Start a new search to retry.", "completedAt": utc_now(), "events": [*run.events, {"type": "interrupted", "message": "The backend restarted during this search.", "createdAt": utc_now()}]})
                data.searchRuns = [interrupted if item.id == run.id else item for item in data.searchRuns]
                self.ledger.finish(run.id, "interrupted")
                changed = True
        if changed:
            self._save(data)

    @staticmethod
    def _job_payload(run: AgentRun) -> dict[str, object]:
        return {"backendId": run.backendId, "pullRequestId": run.pullRequestId, "action": run.action, "parentRunId": run.parentRunId}

    def _assert_writable_lineage_available(self, data: PersistedAppData, pull_request_id: str, excluding: set[str] | None = None) -> None:
        writable = {"analyze", "rebase", "fix_conflicts", "address_review", "fix_checks", "revise_with_feedback"}
        excluded = excluding or set()
        active = [run for run in data.agentRuns if run.id not in excluded and run.pullRequestId == pull_request_id and run.action in writable and run.status in {"queued", "running", "checks_running", "awaiting_decision", "patch_ready", "awaiting_approval", "approved"} and not run.supersededByRunId]
        if active:
            raise ValueError(f"A writable remediation lineage is already active for this PR ({active[0].id})")

    def _fresh_revision_workspace(self, parent: AgentRun, run_id: str) -> str:
        workspace = Path(parent.workspacePath or "").expanduser().resolve()
        root = RunWorkspace.root.resolve()
        if root in workspace.parents:
            destination_root = root / run_id
            destination = destination_root / "checkout"
            destination_root.mkdir(parents=True, exist_ok=False)
            try:
                shutil.copytree(workspace, destination, dirs_exist_ok=False, ignore=shutil.ignore_patterns(".local", ".config", ".mergeops-bin"))
                return str(destination)
            except Exception:
                shutil.rmtree(destination_root, ignore_errors=True)
                raise
        # Test and legacy workspaces may live outside the managed root. They
        # cannot be safely copied into a production run lineage.
        return str(workspace)

    def _validate_review_selection(self, pull_request: PullRequest, thread_ids: list[str], refresh: bool) -> list[SelectedReviewThread]:
        snapshot = self.get_review_threads(pull_request.id, refresh=refresh)
        if snapshot.stale:
            raise ValueError(f"Review-thread snapshot is stale; refresh before queuing a fix: {snapshot.error or 'refresh failed'}")
        requested = list(dict.fromkeys(thread_ids))
        by_id = {thread.id: thread for thread in snapshot.threads}
        missing = [thread_id for thread_id in requested if thread_id not in by_id]
        if missing:
            raise ValueError(f"Unknown review thread(s): {', '.join(missing)}")
        invalid = [thread.id for thread in (by_id[thread_id] for thread_id in requested) if thread.isResolved or thread.isOutdated]
        if invalid:
            raise ValueError("Selected review thread is already resolved or outdated; refresh and select again")
        captured_at = utc_now()
        return [SelectedReviewThread(threadId=thread.id, body=thread.body[:12000], diffHunk=thread.diffHunk[:20000], path=thread.path, line=thread.line, author=thread.author, authorType=thread.authorType, url=thread.url, capturedAt=captured_at) for thread in (by_id[thread_id] for thread_id in requested)]

    @staticmethod
    def _diff_files(diff: str) -> list[str]:
        files: list[str] = []
        for line in diff.splitlines():
            if not line.startswith("diff --git "):
                continue
            parts = line.split(" ")
            if len(parts) >= 4:
                files.append(parts[3][2:])
        return list(dict.fromkeys(files))

    @staticmethod
    def _parse_disposition_output(output: str | None, selected_ids: set[str]) -> dict[str, ReviewDisposition]:
        if not output:
            return {}
        decoder = json.JSONDecoder()
        candidates: list[object] = []
        for index, character in enumerate(output):
            if character != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(output[index:])
            except json.JSONDecodeError:
                continue
            candidates.append(payload)
        for payload in reversed(candidates):
            items = payload.get("dispositions") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                continue
            parsed: dict[str, ReviewDisposition] = {}
            for item in items:
                if not isinstance(item, dict) or item.get("threadId") not in selected_ids:
                    continue
                try:
                    disposition = ReviewDisposition.model_validate(item)
                except ValueError:
                    continue
                parsed[disposition.threadId] = disposition
            if parsed:
                return parsed
        return {}

    def _build_dispositions(self, run: AgentRun, diff: str, checks: list[CheckResult], output: str | None = None, preserve: bool = False) -> list[ReviewDisposition]:
        selected_ids = {thread.threadId for thread in run.selectedReviewThreads}
        parsed = self._parse_disposition_output(output, selected_ids)
        previous = {item.threadId: item for item in run.dispositions} if preserve else {}
        evidence = [check.name for check in checks if check.status == "passed"]
        dispositions: list[ReviewDisposition] = []
        for thread in run.selectedReviewThreads:
            item = parsed.get(thread.threadId)
            if item is None and thread.threadId in previous and not output:
                item = previous[thread.threadId].model_copy(update={"validationEvidence": evidence or previous[thread.threadId].validationEvidence})
            if item is None:
                item = ReviewDisposition(
                    threadId=thread.threadId,
                    disposition="needs_clarification",
                    explanation="The agent did not provide a structured finding for this thread; human clarification is required before replying.",
                    relatedFiles=[thread.path] if thread.path else [],
                    validationEvidence=evidence,
                )
            dispositions.append(item)
        return dispositions

    @staticmethod
    def _build_reply_drafts(run: AgentRun, dispositions: list[ReviewDisposition], diff_hash: str | None) -> list[ReplyDraft]:
        if not diff_hash:
            return []
        by_id = {item.threadId: item for item in dispositions}
        now = utc_now()
        drafts: list[ReplyDraft] = []
        for thread in run.selectedReviewThreads:
            disposition = by_id.get(thread.threadId)
            if not disposition or disposition.disposition != "addressed":
                continue
            files = ", ".join(disposition.relatedFiles) or "the prepared patch"
            drafts.append(ReplyDraft(id=f"reply-{uuid4().hex[:12]}", threadId=thread.threadId, body=f"Addressed in the MergeOps patch. Updated {files} and validated: {', '.join(disposition.validationEvidence) or 'required checks completed'}.", diffHash=diff_hash, updatedAt=now))
        return drafts

    def get_review_threads(self, pull_request_id: str, refresh: bool = True) -> ReviewThreadSnapshot:
        data = self._load()
        pull_request = next((item for item in data.pullRequests if item.id == pull_request_id), None)
        if pull_request is None:
            raise ValueError("Unknown pull request")
        cached = next((item for item in data.reviewThreadSnapshots if item.pullRequestId == pull_request_id), None)
        if not refresh:
            return cached or ReviewThreadSnapshot(pullRequestId=pull_request_id, fetchedAt="", stale=True, error="No review-thread snapshot has been loaded.")
        if not data.githubPrivate.token:
            return self._mark_review_thread_snapshot_stale(pull_request_id, "GitHub token is not configured.")
        try:
            from .github_sync import GitHubClient
            full_name = pull_request.repositoryFullName or self._pull_request_repository_key(pull_request, data)
            if not full_name or "/" not in full_name:
                raise ValueError("Pull request repository identity is unavailable")
            owner, name = full_name.split("/", 1)
            threads = GitHubClient(data.githubPrivate.token).get_review_threads(owner, name, pull_request.number)
            normalized = [{**thread, "pullRequestId": pull_request_id, "repositoryFullName": full_name, "pullRequestNumber": pull_request.number} for thread in threads]
            snapshot = ReviewThreadSnapshot(pullRequestId=pull_request_id, fetchedAt=utc_now(), threads=[ReviewThread.model_validate(thread) for thread in normalized])
            self._persist_review_thread_snapshot(snapshot, update_unresolved_count=True)
            return snapshot
        except Exception as exc:
            return self._mark_review_thread_snapshot_stale(pull_request_id, str(exc))

    def _persist_review_thread_snapshot(self, snapshot: ReviewThreadSnapshot, update_unresolved_count: bool = False) -> None:
        """Merge a refreshed snapshot into the latest dashboard state.

        GitHub calls intentionally happen outside the lock. Reloading only at
        this merge point prevents a slow refresh from writing an older full
        JSON document over a concurrently completed agent run.
        """
        with self._write_lock:
            data = self._load()
            pull_request_id = snapshot.pullRequestId
            data.reviewThreadSnapshots = [snapshot if item.pullRequestId == pull_request_id else item for item in data.reviewThreadSnapshots]
            if not any(item.pullRequestId == pull_request_id for item in data.reviewThreadSnapshots):
                data.reviewThreadSnapshots.append(snapshot)
            if update_unresolved_count:
                unresolved_count = sum(1 for thread in snapshot.threads if not thread.isResolved and not thread.isOutdated)
                data.pullRequests = [item.model_copy(update={"unresolvedCommentCount": unresolved_count}) if item.id == pull_request_id else item for item in data.pullRequests]
            self._save(data)

    def _mark_review_thread_snapshot_stale(self, pull_request_id: str, error: str) -> ReviewThreadSnapshot:
        with self._write_lock:
            data = self._load()
            cached = next((item for item in data.reviewThreadSnapshots if item.pullRequestId == pull_request_id), None)
            if cached is None:
                return ReviewThreadSnapshot(pullRequestId=pull_request_id, fetchedAt="", stale=True, error=error)
            stale = cached.model_copy(update={"stale": True, "error": error})
            data.reviewThreadSnapshots = [stale if item.pullRequestId == pull_request_id else item for item in data.reviewThreadSnapshots]
            self._save(data)
            return stale

    def cache_review_threads(self, pull_request_id: str, threads: list[dict[str, object]]) -> ReviewThreadSnapshot:
        data = self._load()
        pull_request = next((item for item in data.pullRequests if item.id == pull_request_id), None)
        if pull_request is None:
            raise ValueError("Unknown pull request")
        normalized = [{**thread, "pullRequestId": pull_request_id, "repositoryFullName": pull_request.repositoryFullName or pull_request.repository, "pullRequestNumber": pull_request.number} for thread in threads]
        snapshot = ReviewThreadSnapshot(pullRequestId=pull_request_id, fetchedAt=utc_now(), threads=[ReviewThread.model_validate(thread) for thread in normalized])
        self._persist_review_thread_snapshot(snapshot, update_unresolved_count=True)
        return snapshot

    def app_data(self) -> AppData:
        return self._public(self._load())

    def persisted_data(self) -> PersistedAppData:
        return self._load()

    def queue_agent_run(self, backend_id: str, pull_request_id: str, action: str, review_thread_ids: list[str] | None = None) -> AgentRun:
        data = self._load()
        pull_request = next((item for item in data.pullRequests if item.id == pull_request_id), None)
        if pull_request is None:
            raise ValueError("Unknown pull request")
        run_id = f"run-{uuid4().hex[:12]}"
        enabled_backends = adapter_registry(
            [(backend.id, backend.endpoint) for backend in data.agentBackends if backend.enabled]
        )
        if backend_id not in enabled_backends:
            raise ValueError("Unknown agent backend")
        if action == "review_pr" and backend_id != "codex":
            raise ValueError("Direct PR review is currently available with Codex only")
        selected_threads: list[SelectedReviewThread] = []
        if action == "address_review":
            if not review_thread_ids:
                raise ValueError("Select at least one unresolved review thread")
            selected_threads = self._validate_review_selection(pull_request, review_thread_ids, refresh=True)
            data = self._load()
            pull_request = next(item for item in data.pullRequests if item.id == pull_request_id)
        if action in {"address_review", "rebase", "fix_conflicts", "fix_checks"}:
            self._assert_writable_lineage_available(data, pull_request_id)
        created_at = utc_now()
        run = AgentRun(
            id=run_id,
            backendId=backend_id,
            repository=pull_request.repository,
            pullRequestId=pull_request.id,
            pullRequestNumber=pull_request.number,
            action=action,
            status="queued",
            requester="local user",
            summary=f"Queued {action.replace('_', ' ')} run. Preparing isolated workspace.",
            rootRunId=run_id,
            selectedReviewThreads=selected_threads,
            events=[AgentRunEvent(sequence=1, type="queued", message="Run queued; waiting for an available worker.", createdAt=created_at)],
            createdAt=created_at,
        )
        data.agentRuns.insert(0, run)
        data.actions.insert(0, ActionRecord(
            id=run.id,
            kind="agent_run",
            repository=run.repository,
            pullRequestId=run.pullRequestId,
            pullRequestNumber=run.pullRequestNumber,
            action=run.action,
            status=run.status,
            summary=run.summary,
            events=run.events,
            createdAt=run.createdAt,
        ))
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=f"Agent run {run.action} for {run.repository}#{run.pullRequestNumber} was queued.", actionId=run.id, createdAt=run.createdAt))
        self._cancel_events[run.id] = Event()
        self._save(data)
        # Persist the JSON snapshot before exposing the job to a worker. A
        # worker may claim immediately after enqueue and must be able to load
        # the run it is claiming.
        self.ledger.enqueue(run.id, self._job_payload(run), created_at)
        self.ledger.event(run.id, "queued", run.summary, created_at)
        return run

    def create_agent_run(self, backend_id: str, pull_request_id: str, action: str) -> AgentRun:
        run = self.queue_agent_run(backend_id, pull_request_id, action)
        result = self.execute_agent_run(run.id, backend_id, pull_request_id, action)
        self.ledger.finish(run.id, "cancelled" if result.status == "cancelled" else "finished")
        return result

    def queue_revision(self, backend_id: str, parent_run_id: str, payload: CreateRevisionRequest) -> AgentRun:
        data = self._load()
        parent = next((item for item in data.agentRuns if item.id == parent_run_id), None)
        if parent is None:
            raise ValueError("Unknown agent run")
        if parent.status in {"queued", "running", "awaiting_decision", "pushed", "cancelled"}:
            raise ValueError(f"Run cannot be revised in its current state: {parent.status}")
        if not parent.workspacePath or not parent.diff or not parent.diff.strip():
            raise ValueError("Run has no retained prepared patch to revise")
        if not Path(parent.workspacePath).is_dir():
            raise ValueError("Run workspace is no longer available")
        active_review = next((item for item in data.agentRuns if item.parentRunId == parent.id and item.action == "review_patch" and item.status in {"queued", "running"}), None)
        if active_review:
            raise ValueError(f"Run cannot be revised while patch review {active_review.id} is active")
        enabled_backends = adapter_registry([(backend.id, backend.endpoint) for backend in data.agentBackends if backend.enabled])
        if backend_id not in enabled_backends:
            raise ValueError("Unknown agent backend")
        superseded_ids = {parent.id}
        if parent.action == "review_patch" and parent.parentRunId:
            writable_parent = next((item for item in data.agentRuns if item.id == parent.parentRunId), None)
            if writable_parent is None:
                raise ValueError("Patch review parent is no longer available")
            superseded_ids.add(writable_parent.id)
        self._assert_writable_lineage_available(data, parent.pullRequestId, excluding=superseded_ids)
        created_at = utc_now()
        feedback = AgentFeedback(instruction=payload.instruction.strip(), reason=payload.reason.strip() if payload.reason else None, createdAt=created_at)
        run_id = f"run-{uuid4().hex[:12]}"
        revision_workspace = self._fresh_revision_workspace(parent, run_id)
        run = AgentRun(
            id=run_id, backendId=backend_id, repository=parent.repository,
            pullRequestId=parent.pullRequestId, pullRequestNumber=parent.pullRequestNumber,
            action="revise_with_feedback", status="queued", requester="local user",
            summary=f"Queued revision from feedback for {parent.repository}#{parent.pullRequestNumber}.",
            rootRunId=parent.rootRunId or parent.id, parentRunId=parent.id, feedback=feedback, workspacePath=revision_workspace,
            baseCommit=parent.baseCommit,
            selectedReviewThreads=parent.selectedReviewThreads,
            dispositions=parent.dispositions,
            events=[AgentRunEvent(sequence=1, type="queued", message="Feedback revision queued; waiting for an available worker.", createdAt=created_at)],
            createdAt=created_at,
        )
        data.agentRuns = [item.model_copy(update={"status": "superseded", "supersededByRunId": run.id, "approval": None, "summary": f"Superseded by revision {run.id}; prior approval is invalid."}) if item.id in superseded_ids else item for item in data.agentRuns]
        data.actions = [item.model_copy(update={"status": "superseded", "summary": f"Superseded by revision {run.id}; prior approval is invalid.", "approval": None, "supersededByRunId": run.id}) if item.id in superseded_ids else item for item in data.actions]
        data.agentRuns.insert(0, run)
        data.actions.insert(0, ActionRecord(id=run.id, kind="agent_run", repository=run.repository, pullRequestId=run.pullRequestId, pullRequestNumber=run.pullRequestNumber, action=run.action, status=run.status, summary=run.summary, parentRunId=run.parentRunId, feedback=run.feedback, workspacePath=run.workspacePath, baseCommit=run.baseCommit, events=run.events, createdAt=run.createdAt))
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_feedback", message=f"Feedback revision queued for {run.repository}#{run.pullRequestNumber}.", actionId=run.id, createdAt=created_at))
        self._cancel_events[run.id] = Event()
        self._save(data)
        self.ledger.enqueue(run.id, self._job_payload(run), created_at)
        self.ledger.event(run.id, "queued", run.summary, created_at)
        return run

    def queue_patch_review(self, backend_id: str, parent_run_id: str) -> AgentRun:
        data = self._load()
        parent = next((item for item in data.agentRuns if item.id == parent_run_id), None)
        if parent is None:
            raise ValueError("Unknown agent run")
        if not parent.workspacePath:
            raise ValueError("Run has no isolated workspace to review")
        if not parent.diff or not parent.diff.strip():
            raise ValueError("Run has no patch diff to review")
        enabled_backends = adapter_registry(
            [(backend.id, backend.endpoint) for backend in data.agentBackends if backend.enabled]
        )
        if backend_id not in enabled_backends:
            raise ValueError("Unknown agent backend")
        run_id = f"review-{uuid4().hex[:12]}"
        created_at = utc_now()
        review_workspace = self._fresh_revision_workspace(parent, run_id)
        run = AgentRun(
            id=run_id,
            backendId=backend_id,
            repository=parent.repository,
            pullRequestId=parent.pullRequestId,
            pullRequestNumber=parent.pullRequestNumber,
            action="review_patch",
            status="queued",
            requester="local user",
            summary=f"Queued patch review for {parent.repository}#{parent.pullRequestNumber}.",
            rootRunId=parent.rootRunId or parent.id,
            parentRunId=parent.id,
            workspacePath=review_workspace,
            baseCommit=parent.baseCommit,
            diffHash=parent.diffHash,
            selectedReviewThreads=parent.selectedReviewThreads,
            events=[AgentRunEvent(sequence=1, type="queued", message="Patch review queued; waiting for an available worker.", createdAt=created_at)],
            patchSummary=parent.patchSummary,
            diff=parent.diff,
            checks=parent.checks,
            riskSummary=parent.riskSummary,
            createdAt=created_at,
        )
        data.agentRuns.insert(0, run)
        data.actions.insert(0, ActionRecord(
            id=run.id,
            kind="agent_run",
            repository=run.repository,
            pullRequestId=run.pullRequestId,
            pullRequestNumber=run.pullRequestNumber,
            action=run.action,
            status=run.status,
            summary=run.summary,
            parentRunId=run.parentRunId,
            workspacePath=run.workspacePath,
            baseCommit=run.baseCommit,
            events=run.events,
            patchSummary=run.patchSummary,
            diff=run.diff,
            checks=run.checks,
            riskSummary=run.riskSummary,
            createdAt=run.createdAt,
        ))
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=f"Patch review for {parent.repository}#{parent.pullRequestNumber} was queued.", actionId=run.id, createdAt=run.createdAt))
        self._cancel_events[run.id] = Event()
        self._save(data)
        self.ledger.enqueue(run.id, self._job_payload(run), created_at)
        self.ledger.event(run.id, "queued", run.summary, created_at)
        return run

    def execute_patch_review(self, run_id: str, backend_id: str, parent_run_id: str) -> AgentRun:
        data = self._load()
        parent = next((item for item in data.agentRuns if item.id == parent_run_id), None)
        run = next((item for item in data.agentRuns if item.id == run_id), None)
        if parent is None or run is None:
            raise ValueError("Unknown patch review run")
        pull_request = next((item for item in data.pullRequests if item.id == parent.pullRequestId), None)
        if pull_request is None:
            raise ValueError("Unknown pull request")
        adapter = adapter_registry([(backend.id, backend.endpoint) for backend in data.agentBackends if backend.enabled]).get(backend_id)
        if adapter is None:
            raise ValueError("Unknown agent backend")
        cancel_event = self._cancel_events.setdefault(run_id, Event())
        self.ledger.heartbeat(run_id, self._worker_owner)
        started_at = utc_now()
        running = run.model_copy(update={
            "status": "running",
            "summary": "Worker started; reviewing the prepared patch.",
            "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type="running", message="Worker started; reviewing the prepared patch.", createdAt=started_at)],
        })
        data.agentRuns = [running if item.id == run_id else item for item in data.agentRuns]
        data.actions = [item.model_copy(update={"status": running.status, "summary": running.summary, "events": running.events}) if item.id == run_id else item for item in data.actions]
        self._save(data)
        try:
            result = adapter.create_run(AgentRunRequest(
                run_id=run_id,
                pull_request_id=parent.pullRequestId,
                repository=pull_request.repositoryFullName or parent.repository,
                pull_request_number=parent.pullRequestNumber,
                action="review_patch",
                backend_id=backend_id,
                existing_workspace_path=run.workspacePath,
                base_branch=pull_request.baseBranch,
                source_branch=pull_request.sourceBranch,
                review_diff=parent.diff,
                previous_agent_output=parent.agentOutput,
                runner_timeout_seconds=data.agentSettings.runnerTimeoutSeconds,
                process_identity=lambda pid, group: self.ledger.heartbeat(run_id, self._worker_owner, process_pid=pid, process_group=group),
            ), on_event=lambda event: self.append_agent_event(run_id, event), cancel_event=cancel_event)
        except Exception as exc:
            result = AgentRunResult(status="failed", summary=f"Patch review failed: {exc}", events=[{"type": "error", "message": f"Patch review failed: {exc}", "createdAt": utc_now()}])
        with self._write_lock:
            data = self._load()
            current = next((item for item in data.agentRuns if item.id == run_id), running)
            final_status = "cancelled" if cancel_event.is_set() else result.status
            updated = current.model_copy(update={
                "status": final_status,
                "summary": result.summary,
                "agentOutput": result.output,
                "backendSessionId": result.backend_session_id,
                "workspacePath": run.workspacePath,
                "baseCommit": parent.baseCommit,
            })
            data.agentRuns = [updated if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": updated.status, "summary": updated.summary, "agentOutput": updated.agentOutput, "workspacePath": updated.workspacePath, "baseCommit": updated.baseCommit, "events": updated.events}) if item.id == run_id else item for item in data.actions]
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=f"Patch review for {updated.repository}#{updated.pullRequestNumber} is {updated.status}.", actionId=updated.id, createdAt=utc_now()))
            self._save(data)
        return updated

    def execute_agent_run(self, run_id: str, backend_id: str, pull_request_id: str, action: str) -> AgentRun:
        data = self._load()
        pull_request = next((item for item in data.pullRequests if item.id == pull_request_id), None)
        run = next((item for item in data.agentRuns if item.id == run_id), None)
        if pull_request is None or run is None:
            raise ValueError("Unknown agent run")
        parent_run = next((item for item in data.agentRuns if item.id == run.parentRunId), None) if run.parentRunId else None
        repository = self._repository_config(data, self._pull_request_repository_key(pull_request, data))
        adapter = adapter_registry([(backend.id, backend.endpoint) for backend in data.agentBackends if backend.enabled]).get(backend_id)
        if adapter is None:
            raise ValueError("Unknown agent backend")
        cancel_event = self._cancel_events.setdefault(run_id, Event())
        self.ledger.heartbeat(run_id, self._worker_owner)
        started_at = utc_now()
        running = run.model_copy(update={
            "status": "running",
            "summary": "Worker started; preparing isolated workspace and launching agent.",
            "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type="running", message="Worker started; preparing isolated workspace and launching agent.", createdAt=started_at)],
        })
        data.agentRuns = [running if item.id == run_id else item for item in data.agentRuns]
        data.actions = [item.model_copy(update={"status": running.status, "summary": running.summary, "events": running.events}) if item.id == run_id else item for item in data.actions]
        self._save(data)
        existing_workspace_path = None
        rebase_plan = None
        continue_rebase = False
        if action in {"fix_conflicts", "rebase"}:
            try:
                active_workspace = RunWorkspace(Path(run.workspacePath), run.baseCommit or "") if run.workspacePath and Path(run.workspacePath).is_dir() else None
                if run.workspacePath and run.rebaseEvidence and run.rebaseEvidence.plan and active_workspace and (
                    RunWorkspace.rebase_in_progress(active_workspace)
                    or (run.rebaseEvidence.decision and run.rebaseEvidence.decision.selectedOption)
                ):
                    existing_workspace_path = run.workspacePath
                    rebase_plan = run.rebaseEvidence.plan.model_dump(mode="json")
                    continue_rebase = RunWorkspace.rebase_in_progress(active_workspace)
                else:
                    workspace = RunWorkspace.create(AgentRunRequest(
                        run_id=run_id, pull_request_id=pull_request.id, repository=pull_request.repositoryFullName or pull_request.repository,
                        pull_request_number=pull_request.number, action=action, backend_id=backend_id,
                        repository_local_path=repository.localPath if repository else None, repository_remote_url=self._repository_remote_url(pull_request, data),
                        repository_token=data.githubPrivate.token, pull_request_ref=f"refs/pull/{pull_request.number}/head" if repository is None or repository.localPath is None else None,
                        base_branch=pull_request.baseBranch, source_branch=pull_request.sourceBranch,
                    ))
                    base_ref = RunWorkspace.resolve_base_ref(workspace.path, pull_request.baseBranch)
                    preflight = RunWorkspace.rebase_plan(workspace, base_ref)
                    rebase_plan = preflight["plan"]
                    if preflight["decision"]:
                        evidence = RebaseEvidence(baseRef=base_ref, initialHead=workspace.base_commit, state="running", plan=preflight["plan"], decision=preflight["decision"])
                        decision_run = running.model_copy(update={
                            "status": "awaiting_decision", "summary": "Rebase strategy needs a human decision before OpenCode can make changes.",
                            "workspacePath": str(workspace.path), "baseCommit": workspace.base_commit, "rebaseEvidence": evidence,
                            "events": [*running.events, AgentRunEvent(sequence=len(running.events) + 1, type="decision_required", message=evidence.decision.question, createdAt=utc_now())],
                        })
                        data.agentRuns = [decision_run if item.id == run_id else item for item in data.agentRuns]
                        data.actions = [item.model_copy(update={"status": decision_run.status, "summary": decision_run.summary, "workspacePath": decision_run.workspacePath, "baseCommit": decision_run.baseCommit, "events": decision_run.events, "rebaseEvidence": decision_run.rebaseEvidence}) if item.id == run_id else item for item in data.actions]
                        self._save(data)
                        return decision_run
                    existing_workspace_path = str(workspace.path)
            except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
                result = AgentRunResult(status="failed", summary=f"Could not prepare rebase strategy: {exc}", events=[{"type": "error", "message": f"Could not prepare rebase strategy: {exc}", "createdAt": utc_now()}])
            else:
                result = None
        else:
            result = None
        if action == "revise_with_feedback":
            if not run.workspacePath:
                result = AgentRunResult(status="failed", summary="Feedback revision has no retained workspace.")
            else:
                existing_workspace_path = run.workspacePath
        try:
            if result is None:
                result = adapter.create_run(AgentRunRequest(
                run_id=run_id,
                pull_request_id=pull_request.id,
                repository=pull_request.repositoryFullName or pull_request.repository,
                pull_request_number=pull_request.number,
                action=action,
                backend_id=backend_id,
                repository_local_path=repository.localPath if repository else None,
                repository_remote_url=self._repository_remote_url(pull_request, data),
                repository_token=data.githubPrivate.token,
                pull_request_ref=f"refs/pull/{pull_request.number}/head" if repository is None or repository.localPath is None else None,
                base_branch=pull_request.baseBranch,
                source_branch=pull_request.sourceBranch,
                runner_timeout_seconds=data.agentSettings.runnerTimeoutSeconds,
                existing_workspace_path=existing_workspace_path,
                rebase_plan=rebase_plan,
                previous_agent_output=parent_run.agentOutput if parent_run else None,
                feedback_instruction=run.feedback.instruction if run.feedback else None,
                feedback_reason=run.feedback.reason if run.feedback else None,
                selected_review_threads=[thread.model_dump(mode="json") for thread in run.selectedReviewThreads],
                continue_rebase=continue_rebase,
                previous_rebase_evidence=run.rebaseEvidence.model_dump(mode="json") if continue_rebase and run.rebaseEvidence else None,
                process_identity=lambda pid, group: self.ledger.heartbeat(run_id, self._worker_owner, process_pid=pid, process_group=group),
            ), on_event=lambda event: self.append_agent_event(run_id, event), cancel_event=cancel_event)
        except Exception as exc:
            result = AgentRunResult(status="failed", summary=f"Agent worker failed: {exc}", events=[{"type": "error", "message": f"Agent worker failed: {exc}", "createdAt": utc_now()}])
        patch_summary = None
        diff = None
        diff_hash = None
        checks: list[CheckResult] = []
        risk_summary = None
        rebase_evidence = RebaseEvidence.model_validate(result.rebase_evidence) if result.rebase_evidence else None
        if result.workspace_path and result.status == "awaiting_approval":
            self.append_agent_event(run_id, {"type": "checks_started", "message": "Running required checks against the prepared workspace."})
            review_base = None
            if (action in {"fix_conflicts", "rebase"} or (action == "revise_with_feedback" and parent_run and parent_run.action in {"fix_conflicts", "rebase"})) and pull_request.baseBranch:
                review_base = f"origin/{pull_request.baseBranch}...HEAD"
            try:
                patch_summary, raw_diff, raw_checks, risk_summary = inspect_workspace(
                    Path(result.workspace_path),
                    repository.requiredChecks if repository else None,
                    review_base,
                )
                diff = raw_diff[:50000] if raw_diff else raw_diff
                # Approval and reply validation operate on the retained diff,
                # so hash exactly that bounded representation.
                diff_hash = hashlib.sha256((diff or "").encode("utf-8")).hexdigest() if diff else None
                if rebase_evidence is not None and raw_diff is not None:
                    rebase_evidence.diff = BoundedText(text=diff or "", truncated=len(raw_diff) > 50000, originalLength=len(raw_diff))
                checks = [CheckResult.model_validate(check) for check in raw_checks]
                if rebase_evidence is not None:
                    rebase_evidence.stages.append({"sequence": len(rebase_evidence.stages) + 1, "type": "checks_completed", "message": f"Completed {len(checks)} required check(s).", "createdAt": utc_now()})
                self.append_agent_event(run_id, {"type": "checks_completed", "message": f"Completed {len(checks)} required check(s)."})
            except (OSError, subprocess.SubprocessError) as exc:
                message = f"Could not inspect the completed workspace: {exc}"
                failure = {"type": "checks_failed", "message": message, "createdAt": utc_now()}
                self.append_agent_event(run_id, failure)
                result = AgentRunResult(
                    status="failed", summary=message, output=result.output, backend_session_id=result.backend_session_id,
                    workspace_path=result.workspace_path, base_commit=result.base_commit,
                    events=[*(result.events or []), failure], rebase_evidence=result.rebase_evidence,
                )
        if rebase_evidence is not None:
            if result.status == "cancelled":
                rebase_evidence.state = "cancelled"
            if result.output:
                rebase_evidence.transcript = BoundedText(text=result.output[-20000:], truncated=len(result.output) > 20000, originalLength=len(result.output))
        with self._write_lock:
            data = self._load()
            current = next((item for item in data.agentRuns if item.id == run_id), running)
            has_patch = bool(diff and diff.strip())
            checks_passed = bool(checks) and all(check.status == "passed" for check in checks)
            final_status = "cancelled" if cancel_event.is_set() else ("patch_ready" if result.status == "awaiting_approval" and has_patch and checks_passed else ("failed" if result.status == "awaiting_approval" else result.status))
            final_events = current.events
            if final_status == "patch_ready" and not any(event.type == "patch_ready" for event in final_events):
                final_events = [*final_events, AgentRunEvent(sequence=len(final_events) + 1, type="patch_ready", message="Patch and check results are ready for human approval.", createdAt=utc_now())]
            if final_status == "failed" and result.status == "awaiting_approval" and not has_patch:
                final_events = [*final_events, AgentRunEvent(sequence=len(final_events) + 1, type="no_patch", message="Agent completed without producing a working-tree patch.", createdAt=utc_now())]
            if final_status == "failed" and result.status == "awaiting_approval" and has_patch and not checks_passed:
                final_events = [*final_events, AgentRunEvent(sequence=len(final_events) + 1, type="checks_failed", message="One or more required checks failed; approval is unavailable.", createdAt=utc_now())]
            final_summary = result.summary
            if result.status == "awaiting_approval" and not has_patch:
                final_summary = "Agent completed without producing a working-tree patch. No approval is available."
            elif result.status == "awaiting_approval" and has_patch and not checks_passed:
                final_summary = "Agent produced a patch, but one or more required checks failed. No approval is available."
            review_lineage = action == "address_review" or (action == "revise_with_feedback" and bool(current.selectedReviewThreads))
            dispositions = self._build_dispositions(
                current,
                diff or "",
                checks,
                result.output,
                preserve=action == "revise_with_feedback" and not result.output,
            ) if review_lineage and has_patch else current.dispositions
            reply_drafts = self._build_reply_drafts(current, dispositions, diff_hash) if review_lineage and final_status == "patch_ready" else current.replyDrafts
            updated = current.model_copy(update={
                "status": final_status,
                "summary": (f"Patch prepared for review. {patch_summary}" if final_status == "patch_ready" and patch_summary else final_summary),
                "agentOutput": result.output,
                "backendSessionId": result.backend_session_id,
                "workspacePath": result.workspace_path,
                "baseCommit": result.base_commit,
                "events": final_events,
                "patchSummary": patch_summary,
                "diff": diff,
                "checks": checks,
                "riskSummary": risk_summary,
                "rebaseEvidence": rebase_evidence,
                "diffHash": diff_hash,
                "dispositions": dispositions,
                "replyDrafts": reply_drafts,
            })
            data.agentRuns = [updated if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": updated.status, "summary": updated.summary, "agentOutput": updated.agentOutput, "workspacePath": updated.workspacePath, "baseCommit": updated.baseCommit, "events": updated.events, "patchSummary": updated.patchSummary, "diff": updated.diff, "checks": updated.checks, "riskSummary": updated.riskSummary, "rebaseEvidence": updated.rebaseEvidence, "diffHash": updated.diffHash, "selectedReviewThreads": updated.selectedReviewThreads, "dispositions": updated.dispositions, "replyDrafts": updated.replyDrafts, "replyResults": updated.replyResults}) if item.id == run_id else item for item in data.actions]
            if checks:
                data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="checks", message=f"Required checks completed for {updated.repository}#{updated.pullRequestNumber}.", actionId=updated.id, createdAt=utc_now()))
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=f"Agent run {updated.action} for {updated.repository}#{updated.pullRequestNumber} is {updated.status}.", actionId=updated.id, createdAt=utc_now()))
            self._save(data)
            self.ledger.event(updated.id, updated.status, updated.summary, utc_now())
        return updated

    def cancel_agent_run(self, run_id: str) -> AgentRun:
        with self._write_lock:
            data = self._load()
            run = next((item for item in data.agentRuns if item.id == run_id), None)
            if run is None:
                raise ValueError("Unknown agent run")
            if run.status not in {"queued", "running", "patch_ready", "checks_running"}:
                return run
            self._cancel_events.setdefault(run_id, Event()).set()
            self.ledger.request_cancel(run_id)
            cancelled = run.model_copy(update={
                "status": "cancelled",
                "summary": "Cancellation requested; stopping the worker.",
                "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type="cancel_requested", message="Cancellation requested; stopping the worker.", createdAt=utc_now())],
            })
            data.agentRuns = [cancelled if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": cancelled.status, "summary": cancelled.summary, "events": cancelled.events}) if item.id == run_id else item for item in data.actions]
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=f"Cancellation requested for {run.repository}#{run.pullRequestNumber}.", actionId=run.id, createdAt=utc_now()))
            self._save(data)
            self.ledger.event(run.id, "cancel_requested", "Cancellation requested; stopping the worker.", cancelled.createdAt)
            return cancelled

    def retry_agent_run(self, run_id: str) -> AgentRun:
        data = self._load()
        parent = next((item for item in data.agentRuns if item.id == run_id), None)
        if parent is None:
            raise ValueError("Unknown agent run")
        if parent.status not in {"failed", "cancelled", "interrupted", "recovery_required"}:
            raise ValueError(f"Only failed or interrupted runs can be retried: {parent.status}")
        if parent.status == "recovery_required" and not parent.recoveryInspected:
            raise ValueError("Recovery is required: inspect the retained workspace and confirm the old runner is gone before retrying")
        if parent.action == "address_review":
            selected = self._validate_review_selection(next(item for item in data.pullRequests if item.id == parent.pullRequestId), [item.threadId for item in parent.selectedReviewThreads], refresh=True)
            data = self._load()
            parent = next(item for item in data.agentRuns if item.id == run_id)
        else:
            selected = parent.selectedReviewThreads
        created_at = utc_now()
        retry_id = f"run-{uuid4().hex[:12]}"
        workspace_path = None
        base_commit = parent.baseCommit
        excluded_lineage = {parent.id}
        if parent.action in {"review_patch", "revise_with_feedback"}:
            workspace_source = parent
            if parent.parentRunId:
                source_parent = next((item for item in data.agentRuns if item.id == parent.parentRunId), None)
                if source_parent and source_parent.workspacePath:
                    workspace_source = source_parent
                    excluded_lineage.add(source_parent.id)
            if not workspace_source.workspacePath or not Path(workspace_source.workspacePath).is_dir():
                raise ValueError("Retry source workspace is no longer available")
            workspace_path = self._fresh_revision_workspace(workspace_source, retry_id)
            base_commit = workspace_source.baseCommit or base_commit
        self._assert_writable_lineage_available(data, parent.pullRequestId, excluding=excluded_lineage)
        retry = AgentRun(
            id=retry_id, backendId=parent.backendId, repository=parent.repository,
            pullRequestId=parent.pullRequestId, pullRequestNumber=parent.pullRequestNumber, action=parent.action,
            status="queued", requester="local user", summary=f"Retry queued for {parent.repository}#{parent.pullRequestNumber}.",
            rootRunId=parent.rootRunId or parent.id, parentRunId=parent.id, feedback=parent.feedback,
            workspacePath=workspace_path, baseCommit=base_commit, selectedReviewThreads=selected,
            dispositions=parent.dispositions,
            events=[AgentRunEvent(sequence=1, type="queued", message="Retry queued with a fresh isolated workspace.", createdAt=created_at)], createdAt=created_at,
        )
        data.agentRuns.insert(0, retry)
        data.actions.insert(0, ActionRecord(id=retry.id, kind="agent_run", repository=retry.repository, pullRequestId=retry.pullRequestId, pullRequestNumber=retry.pullRequestNumber, action=retry.action, status=retry.status, summary=retry.summary, rootRunId=retry.rootRunId, parentRunId=retry.parentRunId, feedback=retry.feedback, workspacePath=retry.workspacePath, baseCommit=retry.baseCommit, selectedReviewThreads=retry.selectedReviewThreads, dispositions=retry.dispositions, events=retry.events, createdAt=retry.createdAt))
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=retry.summary, actionId=retry.id, createdAt=created_at))
        self._cancel_events[retry.id] = Event()
        self._save(data)
        self.ledger.enqueue(retry.id, self._job_payload(retry), created_at)
        self.ledger.event(retry.id, "retry_queued", retry.summary, created_at)
        return retry

    def revalidate_manual_run(self, run_id: str) -> AgentRun:
        """Validate a manually completed rebase without rerunning the agent."""
        with self._write_lock:
            data = self._load()
            run = next((item for item in data.agentRuns if item.id == run_id), None)
            if run is None:
                raise ValueError("Unknown agent run")
            if run.status != "failed" or run.action not in {"fix_conflicts", "rebase"}:
                raise ValueError("Only failed conflict-fix or rebase runs can be fixed manually")
            if not run.workspacePath or not Path(run.workspacePath).is_dir():
                raise ValueError("The retained workspace is no longer available")
            workspace = RunWorkspace(Path(run.workspacePath), run.baseCommit or "")
            unresolved = RunWorkspace.unmerged_files(workspace)
            if RunWorkspace.rebase_in_progress(workspace) or unresolved:
                detail = f"; unresolved files remain: {', '.join(unresolved)}" if unresolved else ""
                raise ValueError(f"Manual rebase is not complete{detail}")
            RunWorkspace.strip_runtime_from_head(workspace)
            pull_request = next((item for item in data.pullRequests if item.id == run.pullRequestId), None)
            if pull_request is None:
                raise ValueError("Pull request no longer exists")
            repository = self._repository_config(data, pull_request.repositoryFullName or pull_request.repository)
            review_base = f"origin/{pull_request.baseBranch}...HEAD" if pull_request.baseBranch else None
            patch_summary, raw_diff, raw_checks, risk_summary = inspect_workspace(workspace.path, repository.requiredChecks if repository else None, review_base)
            diff = raw_diff[:50000] if raw_diff else raw_diff
            checks = [CheckResult.model_validate(check) for check in raw_checks]
            if not diff or not diff.strip():
                raise ValueError("The manually resolved workspace has no patch to approve")
            if any(check.status != "passed" for check in checks):
                raise ValueError("Manual workspace checks must all pass before approval")
            evidence = run.rebaseEvidence.model_copy(update={"state": "completed", "finalHead": RunWorkspace._git(workspace.path, "rev-parse", "HEAD").strip()}) if run.rebaseEvidence else None
            now = utc_now()
            event = AgentRunEvent(sequence=len(run.events) + 1, type="manual_revalidated", message="Manual conflict resolution validated; patch is ready for human approval.", createdAt=now)
            updated = run.model_copy(update={"status": "patch_ready", "summary": f"Manually resolved patch ready for approval. {patch_summary}", "events": [*run.events, event], "patchSummary": patch_summary, "diff": diff, "checks": checks, "riskSummary": risk_summary, "diffHash": hashlib.sha256(diff.encode("utf-8")).hexdigest(), "approval": None, "rebaseEvidence": evidence})
            data.agentRuns = [updated if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": updated.status, "summary": updated.summary, "events": updated.events, "patchSummary": updated.patchSummary, "diff": updated.diff, "checks": updated.checks, "riskSummary": updated.riskSummary, "diffHash": updated.diffHash, "approval": None, "rebaseEvidence": updated.rebaseEvidence}) if item.id == run_id else item for item in data.actions]
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=f"Manual conflict resolution validated for {updated.repository}#{updated.pullRequestNumber}; approval is required.", actionId=updated.id, createdAt=now))
            self._save(data)
            self.ledger.event(updated.id, "patch_ready", updated.summary, now)
            return updated

    def continue_rebase(self, run_id: str) -> AgentRun:
        """Queue OpenCode to continue an active rebase in the retained workspace."""
        with self._write_lock:
            data = self._load()
            run = next((item for item in data.agentRuns if item.id == run_id), None)
            if run is None:
                raise ValueError("Unknown agent run")
            if run.status != "failed" or run.action not in {"fix_conflicts", "rebase"}:
                raise ValueError("Only failed conflict-fix or rebase runs can be continued")
            if not run.workspacePath or not Path(run.workspacePath).is_dir():
                raise ValueError("The retained workspace is no longer available")
            workspace = RunWorkspace.from_existing(run.workspacePath)
            if not RunWorkspace.rebase_in_progress(workspace):
                raise ValueError("The retained workspace has no active rebase; use Fixed manually or retry with a fresh workspace")
            if not run.rebaseEvidence or not run.rebaseEvidence.plan:
                raise ValueError("The retained run has no rebase plan to continue")
            now = utc_now()
            continued = run.model_copy(update={
                "status": "queued",
                "summary": "Rebase continuation queued; OpenCode will continue the active rebase in the retained workspace.",
                "rebaseEvidence": run.rebaseEvidence.model_copy(update={"state": "running"}),
                "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type="rebase_continue_queued", message="Queued OpenCode to continue the active rebase in the retained workspace.", createdAt=now)],
            })
            data.agentRuns = [continued if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": continued.status, "summary": continued.summary, "events": continued.events, "rebaseEvidence": continued.rebaseEvidence}) if item.id == run_id else item for item in data.actions]
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=continued.summary, actionId=continued.id, createdAt=now))
            self._cancel_events[run_id] = Event()
            self._save(data)
            self.ledger.enqueue(run_id, self._job_payload(continued), now)
            self.ledger.event(run_id, "rebase_continue_queued", continued.summary, now)
            return continued

    def inspect_recovery(self, run_id: str, confirmed: bool) -> AgentRun:
        if not confirmed:
            raise ValueError("Recovery inspection must be explicitly confirmed")
        with self._write_lock:
            data = self._load()
            run = next((item for item in data.agentRuns if item.id == run_id), None)
            if run is None:
                raise ValueError("Unknown agent run")
            if run.status != "recovery_required":
                raise ValueError(f"Run does not require recovery inspection: {run.status}")
            inspected = run.model_copy(update={
                "recoveryInspected": True,
                "recoveryNote": "A local user confirmed that no old runner remains and the retained workspace may be retried.",
                "summary": "Recovery inspected; retry is available with a fresh isolated workspace.",
                "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type="recovery_inspected", message="A local user confirmed the old runner is gone; retry is now available.", createdAt=utc_now())],
            })
            data.agentRuns = [inspected if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": inspected.status, "summary": inspected.summary, "events": inspected.events, "recoveryNote": inspected.recoveryNote, "recoveryInspected": True}) if item.id == run_id else item for item in data.actions]
            self._save(data)
            self.ledger.event(run_id, "recovery_inspected", inspected.summary, utc_now())
            return inspected

    def select_rebase_decision(self, run_id: str, option_id: str) -> AgentRun:
        with self._write_lock:
            data = self._load()
            run = next((item for item in data.agentRuns if item.id == run_id), None)
            if run is None or run.status != "awaiting_decision" or run.rebaseEvidence is None or run.rebaseEvidence.decision is None:
                raise ValueError("Run is not awaiting a rebase decision")
            valid = {option.id for option in run.rebaseEvidence.decision.options}
            if option_id not in valid:
                raise ValueError("Unsupported rebase decision")
            if option_id == "manual":
                updated = run.model_copy(update={"status": "cancelled", "summary": "Rebase left for manual handling.", "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type="decision_selected", message="Manual handling selected; no Git changes were made.", createdAt=utc_now())]})
            else:
                evidence = run.rebaseEvidence.model_copy(update={"decision": run.rebaseEvidence.decision.model_copy(update={"selectedOption": option_id})})
                updated = run.model_copy(update={"status": "queued", "summary": "Rebase strategy approved; launching OpenCode.", "rebaseEvidence": evidence, "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type="decision_selected", message="Drop old base sync merge selected.", createdAt=utc_now())]})
            data.agentRuns = [updated if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": updated.status, "summary": updated.summary, "events": updated.events, "rebaseEvidence": updated.rebaseEvidence}) if item.id == run_id else item for item in data.actions]
            self._save(data)
            if updated.status == "queued":
                self.ledger.enqueue(updated.id, self._job_payload(updated), utc_now())
            return updated

    def approve_agent_run(self, run_id: str, reviewer: str = "local user") -> AgentRun:
        with self._write_lock:
            data = self._load()
            run = next((item for item in data.agentRuns if item.id == run_id), None)
            if run is None:
                raise ValueError("Unknown agent run")
            if run.status not in {"patch_ready", "awaiting_approval"}:
                raise ValueError(f"Run is not ready for approval: {run.status}")
            if not run.diff or not run.diff.strip():
                raise ValueError("A non-empty patch is required before approval")
            if not run.checks or any(check.status != "passed" for check in run.checks):
                raise ValueError("All required checks must pass before approval")
            current_diff_hash = hashlib.sha256(run.diff.encode("utf-8")).hexdigest()
            if run.diffHash and run.diffHash != current_diff_hash:
                raise ValueError("The retained diff changed; refresh the run before approval")
            approval = ApprovalRecord(id=f"approval-{uuid4().hex[:12]}", runId=run.id, decision="approved", reviewer=reviewer, baseCommit=run.baseCommit, diffHash=current_diff_hash, createdAt=utc_now())
            approved = run.model_copy(update={"status": "approved", "approval": approval, "summary": f"Approved by {reviewer}; ready to push."})
            data.agentRuns = [approved if item.id == run_id else item for item in data.agentRuns]
            data.approvals.insert(0, approval)
            data.actions = [item.model_copy(update={"status": approved.status, "summary": approved.summary, "approval": approved.approval}) if item.id == run_id else item for item in data.actions]
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="approval", message=f"Approved agent run for {run.repository}#{run.pullRequestNumber} by {reviewer}.", actionId=run.id, createdAt=approval.createdAt))
            self._save(data)
            self.ledger.event(run.id, "approved", approved.summary, approval.createdAt)
            return approved

    def push_agent_run(self, run_id: str, target: str = "pr_branch") -> AgentRun:
        data = self._load()
        run = next((item for item in data.agentRuns if item.id == run_id), None)
        if run is None:
            raise ValueError("Unknown agent run")
        if run.status != "approved" or run.approval is None or run.approval.decision != "approved":
            raise ValueError("Run must have an approval record before push")
        if not run.workspacePath:
            raise ValueError("Run has no isolated workspace to push")
        if run.baseCommit != run.approval.baseCommit:
            raise ValueError("Run base commit changed after approval")
        if run.supersededByRunId:
            raise ValueError("This run was superseded; its approval is no longer valid")
        expected_diff_hash = hashlib.sha256((run.diff or "").encode("utf-8")).hexdigest()
        if run.diffHash and run.diffHash != expected_diff_hash:
            raise ValueError("Run diff changed after approval")
        if run.approval.diffHash and run.approval.diffHash != expected_diff_hash:
            raise ValueError("Run diff changed after approval")
        if target not in {"mergeops_branch", "pr_branch"}:
            raise ValueError("Unsupported push target")
        pull_request = next((item for item in data.pullRequests if item.id == run.pullRequestId), None)
        if pull_request is None:
            raise ValueError("Pull request no longer exists")
        push_ref = f"mergeops/{run.id}" if target == "mergeops_branch" else pull_request.sourceBranch
        try:
            workspace = Path(run.workspacePath)
            if run.diff:
                # Agent tools can leave large local caches/databases in the checkout. Never
                # include those runtime artifacts in an approved source patch.
                excludes = [f":(exclude){prefix}**" for prefix in RunWorkspace.RUNTIME_PATH_PREFIXES]
                excludes.extend(f":(exclude)**/*{suffix}" for suffix in RunWorkspace.RUNTIME_FILE_SUFFIXES)
                RunWorkspace._git(workspace, "add", "-A", "--", ".", *excludes)
                staged_runtime = RunWorkspace._git(workspace, "diff", "--cached", "--name-only").splitlines()
                staged_runtime = sorted(path for path in staged_runtime if RunWorkspace.is_runtime_path(path))
                if staged_runtime:
                    raise ValueError(
                        "Generated runtime files are not allowed in an approved patch: "
                        + ", ".join(staged_runtime[:20])
                        + (" ..." if len(staged_runtime) > 20 else "")
                    )
                if RunWorkspace._git_optional(workspace, "diff", "--cached", "--quiet") is False:
                    RunWorkspace._git(workspace, "commit", "-m", f"MergeOps prepare {run.repository}#{run.pullRequestNumber}")
            committed_runtime = RunWorkspace.runtime_files_in_diff(workspace, run.baseCommit or "HEAD")
            if committed_runtime:
                raise ValueError(
                    "Generated runtime files are already committed in this run: "
                    + ", ".join(committed_runtime[:20])
                    + (" ..." if len(committed_runtime) > 20 else "")
                )
            if target == "pr_branch":
                if not pull_request.headRepositoryFullName or not pull_request.sourceBranch:
                    raise ValueError("The PR head repository and source branch are required for a direct PR-branch push")
                remote_url = f"https://github.com/{pull_request.headRepositoryFullName}.git"
                RunWorkspace._git(workspace, "remote", "remove", "mergeops-pr-head") if RunWorkspace._git_optional(workspace, "remote", "get-url", "mergeops-pr-head") else None
                RunWorkspace._git(workspace, "remote", "add", "mergeops-pr-head", remote_url)
                RunWorkspace._git(workspace, "fetch", "--no-tags", "mergeops-pr-head", pull_request.sourceBranch, token=data.githubPrivate.token)
                remote_tip = RunWorkspace._git(workspace, "rev-parse", "FETCH_HEAD").strip()
                # A rebase intentionally rewrites the PR branch. The lease protects against
                # someone else updating it after our fetch without requiring a fast-forward.
                RunWorkspace._git(workspace, "push", "--porcelain", f"--force-with-lease=refs/heads/{push_ref}:{remote_tip}", "mergeops-pr-head", f"HEAD:refs/heads/{push_ref}", token=data.githubPrivate.token, timeout_seconds=30)
            else:
                RunWorkspace._git(workspace, "push", "origin", f"HEAD:refs/heads/{push_ref}", token=data.githubPrivate.token, timeout_seconds=30)
        except Exception as exc:
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="push", message=f"Push failed for {run.repository}#{run.pullRequestNumber}: {exc}", actionId=run.id, createdAt=utc_now()))
            self._save(data)
            raise ValueError(f"Push failed: {exc}") from exc
        destination = "the PR branch" if target == "pr_branch" else f"{push_ref}"
        pushed_commit_sha = RunWorkspace._git(workspace, "rev-parse", "HEAD").strip()
        effective_approval = run.approval.model_copy(update={"diffHash": expected_diff_hash}) if run.approval.diffHash is None else run.approval
        pushed = run.model_copy(update={"status": "pushed", "pushRef": push_ref, "pushedCommitSha": pushed_commit_sha, "diffHash": expected_diff_hash, "approval": effective_approval, "summary": f"Pushed approved patch to {destination}."})
        data.agentRuns = [pushed if item.id == run_id else item for item in data.agentRuns]
        data.actions = [item.model_copy(update={"status": pushed.status, "summary": pushed.summary, "approval": pushed.approval, "pushRef": pushed.pushRef, "pushedCommitSha": pushed.pushedCommitSha}) if item.id == run_id else item for item in data.actions]
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="push", message=f"Pushed approved run for {run.repository}#{run.pullRequestNumber} to {push_ref}.", actionId=run.id, createdAt=utc_now()))
        self._save(data)
        self.ledger.event(run.id, "pushed", pushed.summary, utc_now())
        return pushed

    def post_review_replies(self, run_id: str, payload: PostReviewRepliesRequest) -> AgentRun:
        data = self._load()
        run = next((item for item in data.agentRuns if item.id == run_id), None)
        if run is None:
            raise ValueError("Unknown agent run")
        if run.status != "pushed" or not run.pushedCommitSha:
            raise ValueError("Replies are available only after a successful approved push")
        if not run.diffHash:
            raise ValueError("Run has no final diff hash")
        supplied = {draft.id: draft for draft in payload.replies}
        drafts = {draft.id: draft for draft in run.replyDrafts}
        if any(draft_id not in drafts for draft_id in supplied):
            raise ValueError("Reply draft does not belong to this run")
        if any(draft.diffHash != run.diffHash for draft in supplied.values()):
            raise ValueError("Reply draft is stale because the final diff changed")
        snapshot = self.get_review_threads(run.pullRequestId, refresh=True)
        if snapshot.stale:
            raise ValueError(f"Review-thread refresh failed; replies are blocked until GitHub data is fresh: {snapshot.error or 'refresh failed'}")
        data = self._load()
        run = next(item for item in data.agentRuns if item.id == run_id)
        by_thread = {thread.id: thread for thread in snapshot.threads}
        from .github_sync import GitHubClient
        client = GitHubClient(data.githubPrivate.token)
        results = list(run.replyResults)
        updated_drafts = list(run.replyDrafts)
        for draft_id, submitted in supplied.items():
            draft = drafts[draft_id]
            thread = by_thread.get(draft.threadId)
            now = utc_now()
            if draft.status == "posted":
                result = ReplyResult(draftId=draft_id, threadId=draft.threadId, status="skipped", replyUrl=draft.replyUrl, commitSha=run.pushedCommitSha, createdAt=now)
            elif thread is None or thread.pullRequestId != run.pullRequestId:
                result = ReplyResult(draftId=draft_id, threadId=draft.threadId, status="failed", error="Thread is no longer part of this pull request.", commitSha=run.pushedCommitSha, createdAt=now)
            elif thread.isResolved or thread.isOutdated:
                result = ReplyResult(draftId=draft_id, threadId=draft.threadId, status="failed", error="Thread is already resolved or outdated.", commitSha=run.pushedCommitSha, createdAt=now)
            elif not thread.viewerCanReply:
                result = ReplyResult(draftId=draft_id, threadId=draft.threadId, status="failed", error="The current GitHub identity cannot reply to this thread.", commitSha=run.pushedCommitSha, createdAt=now)
            elif any(comment.body.strip() == submitted.body.strip() for comment in thread.comments):
                # An earlier mutation may have succeeded while its response
                # was lost. Treat a matching existing comment as posted so a
                # retry cannot create a duplicate GitHub reply.
                duplicate = next(comment for comment in thread.comments if comment.body.strip() == submitted.body.strip())
                result = ReplyResult(draftId=draft_id, threadId=draft.threadId, status="posted", replyUrl=duplicate.url, commitSha=run.pushedCommitSha, createdAt=now)
            else:
                try:
                    reply = client.add_thread_reply(thread.id, submitted.body.strip())
                    result = ReplyResult(draftId=draft_id, threadId=draft.threadId, status="posted", replyUrl=str(reply.get("url") or "") or None, commitSha=run.pushedCommitSha, createdAt=now)
                except Exception as exc:
                    # Network outcomes are intentionally ambiguous. The next
                    # refresh/retry must revalidate the thread first.
                    result = ReplyResult(draftId=draft_id, threadId=draft.threadId, status="ambiguous", error=str(exc), commitSha=run.pushedCommitSha, createdAt=now)
            results = [item for item in results if item.draftId != draft_id] + [result]
            updated_drafts = [item.model_copy(update={"body": submitted.body, "status": result.status, "replyUrl": result.replyUrl, "error": result.error, "updatedAt": now}) if item.id == draft_id else item for item in updated_drafts]
        updated = run.model_copy(update={"replyDrafts": updated_drafts, "replyResults": results})
        data.agentRuns = [updated if item.id == run_id else item for item in data.agentRuns]
        data.actions = [item.model_copy(update={"replyDrafts": updated.replyDrafts, "replyResults": updated.replyResults}) if item.id == run_id else item for item in data.actions]
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="review_reply", message=f"Posted review replies for {run.repository}#{run.pullRequestNumber}; inspect individual outcomes.", actionId=run.id, createdAt=utc_now()))
        self._save(data)
        return updated

    def append_agent_event(self, run_id: str, event: dict[str, object]) -> None:
        with self._write_lock:
            data = self._load()
            run = next((item for item in data.agentRuns if item.id == run_id), None)
            if run is None:
                return
            recorded = AgentRunEvent(
                sequence=len(run.events) + 1,
                type=str(event.get("type", "log")),
                message=str(event.get("message", "")),
                createdAt=event.get("createdAt") if isinstance(event.get("createdAt"), str) else utc_now(),
            )
            self.ledger.event(run_id, recorded.type, recorded.message, recorded.createdAt)
            process_pid = event.get("processPid")
            process_group = event.get("processGroup")
            if isinstance(process_pid, int):
                self.ledger.heartbeat(run_id, self._worker_owner, process_pid=process_pid, process_group=process_group if isinstance(process_group, int) else process_pid)
            updated = run.model_copy(update={"events": [*run.events, recorded]})
            data.agentRuns = [updated if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"events": updated.events}) if item.id == run_id else item for item in data.actions]
            self._save(data)

    def action_details(self, action_id: str) -> AgentRun | ActionRecord:
        data = self._load()
        run = next((item for item in data.agentRuns if item.id == action_id), None)
        if run is not None:
            return run
        action = next((item for item in data.actions if item.id == action_id), None)
        if action is None:
            raise ValueError("Unknown action")
        return action

    def pr_annotations(self, pull_request_id: str) -> PrAnnotations:
        data = self._load()
        if not any(item.id == pull_request_id for item in data.pullRequests):
            raise ValueError("Unknown pull request")
        return next((item for item in data.prAnnotations if item.pullRequestId == pull_request_id), PrAnnotations(pullRequestId=pull_request_id))

    def update_pr_tags(self, pull_request_id: str, tags: list[str]) -> PrAnnotations:
        with self._write_lock:
            data = self._load()
            if not any(item.id == pull_request_id for item in data.pullRequests):
                raise ValueError("Unknown pull request")
            normalized = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))[:30]
            existing = self.pr_annotations(pull_request_id)
            updated = existing.model_copy(update={"tags": normalized})
            data.prAnnotations = [updated if item.pullRequestId == pull_request_id else item for item in data.prAnnotations]
            if not any(item.pullRequestId == pull_request_id for item in data.prAnnotations):
                data.prAnnotations.append(updated)
            self._save(data)
            return updated

    def create_pr_note(self, pull_request_id: str, payload: CreatePrNoteRequest) -> PrAnnotations:
        with self._write_lock:
            data = self._load()
            current = self.pr_annotations(pull_request_id)
            created_at = utc_now()
            note = PrNote(id=f"note-{uuid4().hex[:12]}", text=payload.text.strip(), createdAt=created_at, updatedAt=created_at)
            updated = current.model_copy(update={"notes": [note, *current.notes]})
            data.prAnnotations = [updated if item.pullRequestId == pull_request_id else item for item in data.prAnnotations]
            if not any(item.pullRequestId == pull_request_id for item in data.prAnnotations):
                data.prAnnotations.append(updated)
            self._save(data)
            return updated

    def update_pr_note(self, pull_request_id: str, note_id: str, payload: UpdatePrNoteRequest) -> PrAnnotations:
        with self._write_lock:
            data = self._load()
            current = self.pr_annotations(pull_request_id)
            if not any(note.id == note_id for note in current.notes):
                raise ValueError("Unknown PR note")
            updated = current.model_copy(update={"notes": [note.model_copy(update={"text": payload.text.strip(), "updatedAt": utc_now()}) if note.id == note_id else note for note in current.notes]})
            data.prAnnotations = [updated if item.pullRequestId == pull_request_id else item for item in data.prAnnotations]
            self._save(data)
            return updated

    def delete_pr_note(self, pull_request_id: str, note_id: str) -> PrAnnotations:
        with self._write_lock:
            data = self._load()
            current = self.pr_annotations(pull_request_id)
            if not any(note.id == note_id for note in current.notes):
                raise ValueError("Unknown PR note")
            updated = current.model_copy(update={"notes": [note for note in current.notes if note.id != note_id]})
            data.prAnnotations = [updated if item.pullRequestId == pull_request_id else item for item in data.prAnnotations]
            self._save(data)
            return updated

    def create_checkout(self, pull_request_id: str) -> CheckoutResult:
        data = self._load()
        pull_request = next((item for item in data.pullRequests if item.id == pull_request_id), None)
        if pull_request is None:
            raise ValueError("Unknown pull request")
        repository = self._repository_config(data, self._pull_request_repository_key(pull_request, data))
        request = AgentRunRequest(
            run_id=f"checkout-{uuid4().hex[:12]}",
            pull_request_id=pull_request.id,
            repository=pull_request.repositoryFullName or pull_request.repository,
            pull_request_number=pull_request.number,
            action="analyze",
            backend_id="workspace",
            repository_local_path=repository.localPath if repository else None,
            repository_remote_url=self._repository_remote_url(pull_request, data),
            repository_token=data.githubPrivate.token,
            pull_request_ref=f"refs/pull/{pull_request.number}/head" if repository is None or repository.localPath is None else None,
            base_branch=pull_request.baseBranch,
            source_branch=pull_request.sourceBranch,
        )
        try:
            workspace = RunWorkspace.create(request)
        except Exception as exc:
            raise ValueError(f"Could not create isolated checkout: {exc}") from exc
        action = ActionRecord(
            id=request.run_id,
            kind="checkout",
            repository=pull_request.repository,
            pullRequestId=pull_request.id,
            pullRequestNumber=pull_request.number,
            action="checkout",
            status="ready",
            summary=f"Isolated checkout ready for {pull_request.repository}#{pull_request.number}. No agent was started.",
            workspacePath=str(workspace.path),
            baseCommit=workspace.base_commit,
            createdAt=utc_now(),
        )
        data.actions.insert(0, action)
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="checkout", message=action.summary, actionId=action.id, createdAt=action.createdAt))
        self._save(data)
        return CheckoutResult(
            pullRequestId=pull_request.id,
            status="ready",
            workspacePath=str(workspace.path),
            baseCommit=workspace.base_commit,
            summary=action.summary,
            action=action,
        )

    def _repository_remote_url(self, pull_request: PullRequest, data: PersistedAppData) -> str | None:
        full_name = pull_request.repositoryFullName or self._pull_request_repository_key(pull_request, data)
        return f"https://github.com/{full_name}.git" if full_name else None

    def clear_action(self, action_id: str) -> None:
        with self._write_lock:
            data = self._load()
            action = next((item for item in data.actions if item.id == action_id), None)
            if action is None:
                raise ValueError("Unknown action")
            self._clear_actions(data, [action])
            self._save(data)

    def clear_all_agent_runs(self) -> dict[str, int]:
        with self._write_lock:
            data = self._load()
            terminal_statuses = {"failed", "cancelled", "pushed", "approved", "awaiting_approval", "patch_ready", "review_ready", "recovery_required"}
            clearable = [
                action for action in data.actions
                if action.kind == "agent_run"
                and action.status in terminal_statuses
                and not (action.status == "recovery_required" and not action.recoveryInspected)
            ]
            self._clear_actions(data, clearable)
            if clearable:
                self._save(data)
            return {"cleared": len(clearable), "remaining": len(data.agentRuns)}

    def clear_all_activity(self) -> dict[str, int]:
        with self._write_lock:
            data = self._load()
            cleared = len(data.activity)
            if cleared:
                data.activity = []
                self._save(data)
            return {"cleared": cleared}

    def _clear_actions(self, data: PersistedAppData, actions: list[ActionRecord]) -> None:
        if not actions:
            return
        clear_ids = {action.id for action in actions}
        remaining_actions = [item for item in data.actions if item.id not in clear_ids]
        import shutil
        for action in actions:
            if action.status == "recovery_required" and not action.recoveryInspected:
                raise ValueError("Recovery-required actions must be inspected before cleanup")
            if action.workspacePath and not any(item.workspacePath == action.workspacePath for item in remaining_actions):
                workspace = Path(action.workspacePath).resolve()
                root = RunWorkspace.root.resolve()
                if root not in workspace.parents:
                    raise ValueError("Action workspace is outside the MergeOps workspace root")
                run_root = workspace.parent
                if run_root.exists():
                    shutil.rmtree(run_root)
        data.actions = remaining_actions
        data.agentRuns = [item for item in data.agentRuns if item.id not in clear_ids]
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="action_cleared", message=f"Cleared {len(actions)} agent run action(s).", createdAt=utc_now()))

    def create_team_member(self, payload: CreateTeamMemberRequest) -> TeamMember:
        data = self._load()
        member_id = self._unique_member_id(payload.githubUsername or payload.displayName, data.teamMembers)
        member = TeamMember(id=member_id, **payload.model_dump())
        data.teamMembers.append(member)
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="team", message=f"Added team member {member.displayName}.", createdAt=utc_now()))
        self._save(data)
        return member

    def update_team_member(self, member_id: str, payload: UpdateTeamMemberRequest) -> TeamMember:
        data = self._load()
        index = next((idx for idx, item in enumerate(data.teamMembers) if item.id == member_id), None)
        if index is None:
            raise ValueError("Unknown team member")

        patch = payload.model_dump(exclude_unset=True, exclude_none=True)
        updated = data.teamMembers[index].model_copy(update=patch)
        data.teamMembers[index] = updated
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="team", message=f"Updated team member {updated.displayName}.", createdAt=utc_now()))
        self._save(data)
        return updated

    def delete_team_member(self, member_id: str) -> None:
        data = self._load()
        next_members = [member for member in data.teamMembers if member.id != member_id]
        if len(next_members) == len(data.teamMembers):
            raise ValueError("Unknown team member")
        data.teamMembers = next_members
        fallback_id = next_members[0].id if next_members else "unknown"
        data.pullRequests = [
            pull_request.model_copy(update={"ownerMemberId": fallback_id})
            if pull_request.ownerMemberId == member_id
            else pull_request
            for pull_request in data.pullRequests
        ]
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="team", message=f"Removed team member {member_id}.", createdAt=utc_now()))
        self._save(data)

    def update_github_settings(self, payload: UpdateGitHubSettingsRequest) -> GitHubSettingsPublic:
        data = self._load()
        patch = payload.model_dump(exclude_unset=True)
        if patch.get("token") == "":
            patch.pop("token")
        if patch.get("token") == "__clear__":
            patch["token"] = None
        next_payload = data.githubPrivate.model_dump(mode="json")
        next_payload.update(patch)
        data.githubPrivate = GitHubSettings.model_validate(next_payload)
        data.github = self._public_github(data.githubPrivate)
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="settings", message="GitHub settings updated.", createdAt=utc_now()))
        self._save(data)
        return data.github

    def update_agent_settings(self, payload: UpdateAgentSettingsRequest) -> AgentSettings:
        data = self._load()
        settings = AgentSettings(runnerTimeoutSeconds=max(1, payload.runnerTimeoutSeconds))
        data.agentSettings = settings
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="settings", message=f"Agent runner timeout set to {settings.runnerTimeoutSeconds} seconds.", createdAt=utc_now()))
        self._save(data)
        return settings

    def update_search_settings(self, payload: UpdateSearchSettingsRequest) -> SearchSettingsPublic:
        data = self._load()
        next_settings = data.searchSettingsPrivate.model_dump(mode="json")
        patch = payload.model_dump(exclude_unset=True)
        for key in ("githubReadToken", "gitcodeReadToken"):
            value = patch.get(key)
            if value in (None, ""):
                patch.pop(key, None)
            elif value == "__clear__":
                patch[key] = None
        next_settings.update(patch)
        data.searchSettingsPrivate = SearchSettings.model_validate(next_settings)
        public = self._public_search_settings(data.searchSettingsPrivate)
        data.searchSettings = public
        self._save(data)
        return public

    def queue_search_run(self, backend_id: str, payload: SearchRunRequest) -> SearchRun:
        data = self._load()
        enabled_agent = next((item for item in data.agentBackends if item.id == backend_id and item.enabled), None)
        if enabled_agent is None:
            raise ValueError("Selected agent backend is unavailable")
        settings = data.searchSettingsPrivate
        if settings.backend == "github":
            repositories = [f"{item.owner}/{item.name}" for item in data.githubPrivate.repositories if item.enabled]
            token = settings.githubReadToken
        else:
            repositories = list(dict.fromkeys(value.strip().strip("/") for value in settings.gitcodeRepositories if value.strip()))
            token = settings.gitcodeReadToken
        if not token:
            raise ValueError(f"Add a read-only {settings.backend} search token in Settings → Search")
        selected = list(dict.fromkeys(payload.repositoryIds))
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name) for name in selected):
            raise ValueError("Repositories must use owner/name format")
        unknown = [name for name in selected if name not in repositories]
        if unknown:
            raise ValueError("Search includes repositories that are not configured for the selected backend")
        if payload.memberId:
            selected_member = next((member for member in data.teamMembers if member.id == payload.memberId), None)
            if selected_member is None:
                raise ValueError("Unknown team member filter")
            if not selected_member.githubUsername or not re.fullmatch(r"[A-Za-z0-9_-]+", selected_member.githubUsername):
                raise ValueError("Selected member needs a valid GitHub username for author filtering")
        run_id = f"search-{uuid4().hex[:12]}"
        created = utc_now()
        run = SearchRun(
            id=run_id, backendId=backend_id, searchBackend=settings.backend, query=payload.query.strip(), kind=payload.kind,
            repositoryIds=selected, memberId=payload.memberId, locale=payload.locale, status="queued",
            summary="Search queued.", events=[{"type": "queued", "message": "Search queued.", "createdAt": created}], createdAt=created,
        )
        active = [item for item in data.searchRuns if item.status in {"queued", "running"}]
        history = [item for item in data.searchRuns if item.status not in {"queued", "running"}][:28]
        data.searchRuns = [run, *active, *history]
        self._save(data)
        self.ledger.enqueue(run_id, {"jobType": "search"}, created)
        return run

    def search_run(self, run_id: str) -> SearchRun:
        run = next((item for item in self._load().searchRuns if item.id == run_id), None)
        if run is None:
            raise ValueError("Unknown search run")
        return run

    def cancel_search_run(self, run_id: str) -> SearchRun:
        data = self._load()
        run = next((item for item in data.searchRuns if item.id == run_id), None)
        if run is None:
            raise ValueError("Unknown search run")
        if run.status not in {"queued", "running"}:
            return run
        self.ledger.request_cancel(run_id)
        event = {"type": "cancellation_requested", "message": "Stopping search agent…", "createdAt": utc_now()}
        updated = run.model_copy(update={"summary": "Stopping search agent…", "events": [*run.events, event]})
        data.searchRuns = [updated if item.id == run_id else item for item in data.searchRuns]
        self._cancel_events.setdefault(run_id, Event()).set()
        self._save(data)
        return updated

    def execute_search_run(self, run_id: str) -> SearchRun:
        data = self._load()
        run = next((item for item in data.searchRuns if item.id == run_id), None)
        if run is None:
            raise ValueError("Unknown search run")
        if self.ledger.is_cancel_requested(run_id) or self._cancel_events.setdefault(run_id, Event()).is_set():
            return self._finish_search(run, "cancelled", "Search cancelled before launch.")
        settings = data.searchSettingsPrivate
        token = settings.githubReadToken if run.searchBackend == "github" else settings.gitcodeReadToken
        if not token:
            return self._finish_search(run, "failed", "Read-only search credentials are no longer configured.")
        workspace = Path.home() / ".mergeops" / "search-workspace" / run.id
        run = run.model_copy(update={"status": "running", "summary": "Preparing isolated search workspace…", "workspacePath": str(workspace), "events": [*run.events, {"type": "running", "message": "Preparing isolated search workspace…", "createdAt": utc_now()}]})
        with self._write_lock:
            data = self._load()
            data.searchRuns = [run if item.id == run_id else item for item in data.searchRuns]
            self._save(data)
        repository_names = run.repositoryIds
        member = next((item for item in data.teamMembers if item.id == run.memberId), None) if run.memberId else None
        skill = f"{run.searchBackend}-{'pr' if run.kind == 'pull_requests' else 'issue'}-search"
        input_data = {"searchBackend": run.searchBackend, "kind": run.kind, "query": run.query, "repositories": repository_names, "member": member.githubUsername if member and member.githubUsername else None, "locale": run.locale, "skill": skill}
        adapter = adapter_registry([(item.id, item.endpoint) for item in data.agentBackends if item.enabled]).get(run.backendId)
        if not isinstance(adapter, SubprocessAgentAdapter):
            return self._finish_search(run, "failed", "The selected agent backend does not have a local runner.")
        cancel_event = self._cancel_events.setdefault(run.id, Event())
        def record_event(event: dict[str, object]) -> None:
            with self._write_lock:
                latest = self._load()
                current = next((item for item in latest.searchRuns if item.id == run_id), None)
                if current is None:
                    return
                event_copy = {**event, "sequence": len(current.events) + 1}
                replacement = current.model_copy(update={"summary": str(event.get("message") or current.summary), "events": [*current.events, event_copy]})
                latest.searchRuns = [replacement if item.id == run_id else item for item in latest.searchRuns]
                self._save(latest)
        try:
            result = adapter.create_search_run(run.id, workspace, input_data, token, data.agentSettings.runnerTimeoutSeconds, record_event, cancel_event, process_identity=lambda pid, group: self.ledger.heartbeat(run.id, self._worker_owner, process_pid=pid, process_group=group))
        except Exception as exc:
            self._cleanup_search_workspace(run.id)
            return self._finish_search(run, "failed", f"Search agent failed: {exc}")
        if result.status == "cancelled":
            finished = self._finish_search(run, "cancelled", "Search cancelled.", result.output)
            self._cleanup_search_workspace(run.id)
            return finished
        if result.status != "completed" or not result.output:
            finished = self._finish_search(run, "failed", result.summary, result.output)
            self._cleanup_search_workspace(run.id)
            return finished
        safe_output = result.output.replace(token, "[redacted]") if token else result.output
        try:
            parsed_results, search_errors = self._normalize_search_results(safe_output, run.searchBackend, run.kind, set(repository_names), member.githubUsername if member else None)
        except ValueError as exc:
            finished = self._finish_search(run, "formatting_error", f"The agent completed but returned invalid search results: {exc}", safe_output)
            self._cleanup_search_workspace(run.id)
            return finished
        with self._write_lock:
            latest = self._load()
            current = next(item for item in latest.searchRuns if item.id == run_id)
            summary = f"Found {len(parsed_results)} result(s)." + (f" {len(search_errors)} repository error(s)." if search_errors else "")
            completed = current.model_copy(update={"status": "completed", "summary": summary, "results": parsed_results, "errors": search_errors, "rawOutput": safe_output[-20000:], "workspacePath": None, "completedAt": utc_now(), "events": [*current.events, {"type": "completed", "message": summary, "createdAt": utc_now()}]})
            latest.searchRuns = [completed if item.id == run_id else item for item in latest.searchRuns]
            self._save(latest)
        self._cleanup_search_workspace(run.id)
        return completed

    @staticmethod
    def _cleanup_search_workspace(run_id: str) -> None:
        root = (Path.home() / ".mergeops" / "search-workspace").resolve()
        workspace = (root / run_id).resolve()
        if root in workspace.parents and workspace.name.startswith("search-"):
            shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(root / f".{run_id}.opencode-home", ignore_errors=True)

    def _finish_search(self, run: SearchRun, status: str, message: str, output: str | None = None) -> SearchRun:
        with self._write_lock:
            data = self._load()
            current = next((item for item in data.searchRuns if item.id == run.id), run)
            updated = current.model_copy(update={"status": status, "summary": message, "rawOutput": output[-20000:] if output else current.rawOutput, "completedAt": utc_now(), "events": [*current.events, {"type": status, "message": message, "createdAt": utc_now()}]})
            data.searchRuns = [updated if item.id == run.id else item for item in data.searchRuns]
            self._save(data)
        return updated

    @staticmethod
    def _normalize_search_results(output: str, backend: str, kind: str, repositories: set[str], expected_author: str | None = None) -> tuple[list[SearchResult], list[str]]:
        candidate = output.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`").split("\n", 1)[-1]
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end < start:
            raise ValueError("No JSON result object was found")
        try:
            payload = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("The result JSON could not be parsed") from exc
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or not isinstance(payload.get("results"), list) or not isinstance(payload.get("errors"), list):
            raise ValueError("Expected schemaVersion 1, results, and errors arrays")
        expected_kind = "pull_request" if kind == "pull_requests" else "issue"
        host = "github.com" if backend == "github" else "gitcode.com"
        normalized: list[SearchResult] = []
        seen: set[tuple[str, str, int]] = set()
        errors: list[str] = []
        for error in payload["errors"][:len(repositories)]:
            if not isinstance(error, dict) or error.get("repository") not in repositories or not isinstance(error.get("message"), str) or not error["message"].strip():
                raise ValueError("A repository error is missing its configured repository or message")
            errors.append(f"{error['repository']}: {error['message'][:1000]}")
        for raw in payload["results"][:100]:
            try:
                item = SearchResult.model_validate(raw)
            except Exception as exc:
                raise ValueError("A result is missing required fields or bilingual text") from exc
            parsed = urlparse(item.url)
            if item.source != backend or item.kind != expected_kind or item.repository not in repositories or parsed.hostname != host or not parsed.path.lstrip("/").startswith(item.repository + "/"):
                raise ValueError("A result source, type, repository, or URL is outside the requested search scope")
            if expected_author and item.author.casefold() != expected_author.casefold():
                raise ValueError("A result did not match the selected author filter")
            if not all(item.summary.get(locale, "").strip() for locale in ("en", "zh")) or not all(item.reason.get(locale, "").strip() for locale in ("en", "zh")):
                raise ValueError("Each result needs English and Simplified Chinese summary and relevance text")
            for linked in item.linkedItems:
                linked_url = urlparse(linked.url)
                linked_path = [part for part in linked_url.path.split("/") if part]
                if (
                    linked_url.scheme != "https"
                    or linked_url.hostname != host
                    or linked_url.username is not None
                    or linked_url.password is not None
                    or len(linked_path) < 4
                    or linked_path[-1] != str(linked.number)
                ):
                    raise ValueError("A linked item is outside the selected repository or service")
            key = (backend, item.repository, item.number)
            if key in seen:
                continue
            seen.add(key)
            item.summary = {locale: text[:4000] for locale, text in item.summary.items()}
            item.reason = {locale: text[:1500] for locale, text in item.reason.items()}
            normalized.append(item)
        return normalized, errors

    @staticmethod
    def _public_search_settings(settings: SearchSettings) -> SearchSettingsPublic:
        return SearchSettingsPublic(backend=settings.backend, gitcodeRepositories=settings.gitcodeRepositories, githubReady=bool(settings.githubReadToken), gitcodeReady=bool(settings.gitcodeReadToken))

    def replace_pull_requests(self, pull_requests: list[PullRequest], synced_at: str, errors: list[str]) -> PersistedAppData:
        data = self._load()
        if pull_requests or not errors:
            data.pullRequests = pull_requests
        data.githubPrivate.lastSyncedAt = synced_at
        repositories = []
        for repository in data.githubPrivate.repositories:
            repo_key = f"{repository.owner}/{repository.name}"
            status = "failed" if any(error.startswith(repo_key) for error in errors) else "synced"
            repositories.append(repository.model_copy(update={"lastSyncedAt": synced_at, "lastSyncStatus": status}))
        data.githubPrivate.repositories = repositories
        data.github = self._public_github(data.githubPrivate)
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="sync", message=f"GitHub sync imported {len(pull_requests)} PRs" + (f" with {len(errors)} error(s)." if errors else "."), createdAt=synced_at))
        self._save(data)
        return data

    def _load(self) -> PersistedAppData:
        if not self.path.exists():
            private_github = github_settings
            data = PersistedAppData(
                teamMembers=list(team_members),
                pullRequests=list(pull_requests),
                agentBackends=list(agent_backends),
                agentSettings=AgentSettings(),
                agentRuns=list(agent_runs),
                actions=[ActionRecord(
                    id=run.id,
                    kind="agent_run",
                    repository=run.repository,
                    pullRequestId=run.pullRequestId,
                    pullRequestNumber=run.pullRequestNumber,
                    action=run.action,
                    status=run.status,
                    summary=run.summary,
                    workspacePath=run.workspacePath,
                    baseCommit=run.baseCommit,
                    createdAt=run.createdAt,
                ) for run in agent_runs],
                activity=[ActivityEvent(id=f"activity-{run.id}", kind="agent_run", message=f"Agent run {run.action} for {run.repository}#{run.pullRequestNumber} is {run.status}.", actionId=run.id, createdAt=run.createdAt) for run in agent_runs],
                github=self._public_github(private_github),
                githubPrivate=private_github,
            )
            self._save(data)
            return data

        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if "githubPrivate" not in payload:
            payload["githubPrivate"] = github_settings.model_dump(mode="json")
        if "agentSettings" not in payload:
            payload["agentSettings"] = AgentSettings().model_dump(mode="json")
        legacy_repository_path_fixed = False
        github_payload = payload["githubPrivate"]
        if isinstance(github_payload, dict):
            for repository in github_payload.get("repositories", []):
                if isinstance(repository, dict) and repository.get("localPath") == "git diff --check":
                    repository["localPath"] = None
                    legacy_repository_path_fixed = True
        if "actions" not in payload:
            payload["actions"] = [
                ActionRecord(
                    id=run.id,
                    kind="agent_run",
                    repository=run.repository,
                    pullRequestId=run.pullRequestId,
                    pullRequestNumber=run.pullRequestNumber,
                    action=run.action,
                    status=run.status,
                    summary=run.summary,
                    workspacePath=run.workspacePath,
                    baseCommit=run.baseCommit,
                    createdAt=run.createdAt,
                ).model_dump(mode="json")
                for raw_run in payload.get("agentRuns", [])
                for run in [AgentRun.model_validate(raw_run)]
            ]
        if "activity" not in payload:
            payload["activity"] = [ActivityEvent(id=f"activity-{action.id}", kind=action.kind, message=action.summary, actionId=action.id, createdAt=action.createdAt).model_dump(mode="json") for raw_action in payload.get("actions", []) for action in [ActionRecord.model_validate(raw_action)]]
        if "approvals" not in payload:
            payload["approvals"] = []
        if "prAnnotations" not in payload:
            payload["prAnnotations"] = []
        payload["github"] = self._public_github(GitHubSettings.model_validate(payload["githubPrivate"])).model_dump(mode="json")
        data = PersistedAppData.model_validate(payload)
        action_ids = {action.id for action in data.actions}
        missing_run_actions = [
            ActionRecord(
                id=run.id,
                kind="agent_run",
                repository=run.repository,
                pullRequestId=run.pullRequestId,
                pullRequestNumber=run.pullRequestNumber,
                action=run.action,
                status=run.status,
                summary=run.summary,
                rootRunId=run.rootRunId,
                parentRunId=run.parentRunId,
                feedback=run.feedback,
                workspacePath=run.workspacePath,
                baseCommit=run.baseCommit,
                events=run.events,
                createdAt=run.createdAt,
            )
            for run in data.agentRuns
            if run.id not in action_ids
        ]
        if missing_run_actions:
            data.actions = [*missing_run_actions, *data.actions]
        evidence_migrated = False
        migrated_runs: list[AgentRun] = []
        for run in data.agentRuns:
            evidence = run.rebaseEvidence
            if evidence is None:
                migrated_runs.append(run)
                continue
            conflicts = []
            run_changed = False
            for conflict in evidence.conflicts:
                if conflict.oursHunk.text or conflict.theirsHunk.text or conflict.resultHunk.text:
                    conflicts.append(conflict)
                    continue
                ours, theirs, result = conflict.ours.text, conflict.theirs.text, conflict.result.text
                result_hunk = RunWorkspace._resolved_hunk(ours, theirs, result) if conflict.validationState == "passed" else result
                ours_hunk, theirs_hunk, unresolved_hunk = RunWorkspace._conflict_hunks(ours, theirs, result)
                conflicts.append(conflict.model_copy(update={"oursHunk": BoundedText.model_validate(SubprocessAgentAdapter._bounded(ours_hunk)), "theirsHunk": BoundedText.model_validate(SubprocessAgentAdapter._bounded(theirs_hunk)), "resultHunk": BoundedText.model_validate(SubprocessAgentAdapter._bounded(result_hunk or unresolved_hunk))}))
                run_changed = True
            if run_changed:
                migrated_runs.append(run.model_copy(update={"rebaseEvidence": evidence.model_copy(update={"conflicts": conflicts})}))
                evidence_migrated = True
            else:
                migrated_runs.append(run)
        if evidence_migrated:
            data.agentRuns = migrated_runs
        normalized = [self._normalize_pull_request(pull_request, data) for pull_request in data.pullRequests]
        if normalized != data.pullRequests or legacy_repository_path_fixed or missing_run_actions or evidence_migrated:
            data.pullRequests = normalized
            self._save(data)
        return data

    def _save(self, data: PersistedAppData) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = data.model_dump(mode="json")
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self.path)

    def _public(self, data: PersistedAppData) -> AppData:
        return AppData(
            teamMembers=data.teamMembers,
            pullRequests=data.pullRequests,
            agentBackends=data.agentBackends,
            agentSettings=data.agentSettings,
            agentRuns=[self._run_summary(run) for run in data.agentRuns],
            actions=[self._action_summary(action) for action in data.actions],
            activity=data.activity,
            approvals=data.approvals,
            prTags={item.pullRequestId: item.tags for item in data.prAnnotations if item.tags},
            github=self._public_github(data.githubPrivate),
            searchSettings=self._public_search_settings(data.searchSettingsPrivate),
            searchRuns=data.searchRuns,
        )

    @staticmethod
    def _run_summary(run: AgentRun) -> AgentRunSummary:
        evidence = run.rebaseEvidence
        return AgentRunSummary(
            id=run.id,
            backendId=run.backendId,
            repository=run.repository,
            pullRequestId=run.pullRequestId,
            pullRequestNumber=run.pullRequestNumber,
            action=run.action,
            status=run.status,
            requester=run.requester,
            summary=run.summary,
            rootRunId=run.rootRunId,
            parentRunId=run.parentRunId,
            supersededByRunId=run.supersededByRunId,
            workspacePath=run.workspacePath,
            baseCommit=run.baseCommit,
            diffHash=run.diffHash,
            pushedCommitSha=run.pushedCommitSha,
            createdAt=run.createdAt,
            eventCount=len(run.events),
            checkCount=len(run.checks),
            conflictCount=len(evidence.conflicts) if evidence else 0,
            resolvedConflictCount=sum(1 for item in evidence.conflicts if item.validationState == "passed") if evidence else 0,
            blockedCommandCount=len(evidence.blockedCommands) if evidence else 0,
            hasRebaseEvidence=evidence is not None,
            recoveryInspected=run.recoveryInspected,
        )

    @staticmethod
    def _action_summary(action: ActionRecord) -> ActionSummary:
        evidence = action.rebaseEvidence
        return ActionSummary(
            id=action.id,
            kind=action.kind,
            repository=action.repository,
            pullRequestId=action.pullRequestId,
            pullRequestNumber=action.pullRequestNumber,
            action=action.action,
            status=action.status,
            summary=action.summary,
            rootRunId=action.rootRunId,
            parentRunId=action.parentRunId,
            supersededByRunId=action.supersededByRunId,
            workspacePath=action.workspacePath,
            baseCommit=action.baseCommit,
            createdAt=action.createdAt,
            eventCount=len(action.events),
            checkCount=len(action.checks),
            conflictCount=len(evidence.conflicts) if evidence else 0,
            resolvedConflictCount=sum(1 for item in evidence.conflicts if item.validationState == "passed") if evidence else 0,
            blockedCommandCount=len(evidence.blockedCommands) if evidence else 0,
            hasRebaseEvidence=evidence is not None,
            recoveryInspected=action.recoveryInspected,
            pushRef=action.pushRef,
            diffHash=action.diffHash,
            pushedCommitSha=action.pushedCommitSha,
        )

    def _normalize_pull_request(self, pull_request: PullRequest, data: PersistedAppData) -> PullRequest:
        patch: dict[str, str] = {}
        author = pull_request.author.casefold()
        for member in data.teamMembers:
            identities = [member.githubUsername, *member.gitAliases]
            if any(author == identity.casefold() for identity in identities if identity):
                patch["ownerMemberId"] = member.id
                break
        else:
            if data.githubPrivate.username and author == data.githubPrivate.username.casefold() and len(data.teamMembers) == 1:
                patch["ownerMemberId"] = data.teamMembers[0].id
            else:
                patch["ownerMemberId"] = "unknown"

        if pull_request.repositoryFullName is None:
            repository_full_name = self._unique_repository_full_name(data, pull_request.repository)
            if repository_full_name is not None:
                patch["repositoryFullName"] = repository_full_name

        return pull_request.model_copy(update=patch)

    def _public_github(self, settings: GitHubSettings) -> GitHubSettingsPublic:
        return GitHubSettingsPublic(
            accessMode=settings.accessMode,
            hasToken=bool(settings.token),
            username=settings.username,
            repositories=settings.repositories,
            lastSyncedAt=settings.lastSyncedAt,
        )

    def _repository_config(self, data: PersistedAppData, repository_full_name: str | None) -> RepositoryConfig | None:
        if repository_full_name is None:
            return None
        normalized = repository_full_name.casefold()
        for repository in data.githubPrivate.repositories:
            full_name = f"{repository.owner}/{repository.name}".casefold()
            if normalized == full_name:
                return repository
        return None

    def _pull_request_repository_key(self, pull_request: PullRequest, data: PersistedAppData) -> str | None:
        if pull_request.repositoryFullName:
            return pull_request.repositoryFullName
        return self._unique_repository_full_name(data, pull_request.repository)

    def _unique_repository_full_name(self, data: PersistedAppData, repository_name: str) -> str | None:
        normalized = repository_name.casefold()
        for repository in data.githubPrivate.repositories:
            full_name = f"{repository.owner}/{repository.name}"
            if full_name.casefold() == normalized:
                return full_name
        matches = [
            f"{repository.owner}/{repository.name}"
            for repository in data.githubPrivate.repositories
            if repository.name.casefold() == normalized
        ]
        return matches[0] if len(matches) == 1 else None

    def _unique_member_id(self, seed: str, members: list[TeamMember]) -> str:
        base = "".join(character.lower() if character.isalnum() else "-" for character in seed).strip("-") or "member"
        used = {member.id for member in members}
        if base not in used:
            return base
        suffix = 2
        while f"{base}-{suffix}" in used:
            suffix += 1
        return f"{base}-{suffix}"


store = LocalJsonStore(Path(__file__).resolve().parents[1] / "data" / "mergeops.local.json")

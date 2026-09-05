from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event, Lock
from uuid import uuid4

from .adapters import AgentRunRequest, AgentRunResult, RunWorkspace, adapter_registry, inspect_workspace, utc_now
from .fixtures import agent_backends, agent_runs, github_settings, pull_requests, team_members
from .models import ActionRecord, ActivityEvent, AgentRun, AgentRunEvent, AppData, ApprovalRecord, CheckResult, CheckoutResult, CreateTeamMemberRequest, GitHubSettings, GitHubSettingsPublic, PullRequest, RepositoryConfig, TeamMember, UpdateGitHubSettingsRequest, UpdateTeamMemberRequest


class PersistedAppData(AppData):
    githubPrivate: GitHubSettings


class LocalJsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._write_lock = Lock()
        self._cancel_events: dict[str, Event] = {}

    def app_data(self) -> AppData:
        return self._public(self._load())

    def persisted_data(self) -> PersistedAppData:
        return self._load()

    def queue_agent_run(self, backend_id: str, pull_request_id: str, action: str) -> AgentRun:
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
        return run

    def create_agent_run(self, backend_id: str, pull_request_id: str, action: str) -> AgentRun:
        run = self.queue_agent_run(backend_id, pull_request_id, action)
        return self.execute_agent_run(run.id, backend_id, pull_request_id, action)

    def execute_agent_run(self, run_id: str, backend_id: str, pull_request_id: str, action: str) -> AgentRun:
        data = self._load()
        pull_request = next((item for item in data.pullRequests if item.id == pull_request_id), None)
        run = next((item for item in data.agentRuns if item.id == run_id), None)
        if pull_request is None or run is None:
            raise ValueError("Unknown agent run")
        repository = self._repository_config(data, self._pull_request_repository_key(pull_request, data))
        adapter = adapter_registry([(backend.id, backend.endpoint) for backend in data.agentBackends if backend.enabled]).get(backend_id)
        if adapter is None:
            raise ValueError("Unknown agent backend")
        cancel_event = self._cancel_events.setdefault(run_id, Event())
        started_at = utc_now()
        running = run.model_copy(update={
            "status": "running",
            "summary": "Worker started; preparing isolated workspace and launching agent.",
            "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type="running", message="Worker started; preparing isolated workspace and launching agent.", createdAt=started_at)],
        })
        data.agentRuns = [running if item.id == run_id else item for item in data.agentRuns]
        data.actions = [item.model_copy(update={"status": running.status, "summary": running.summary, "events": running.events}) if item.id == run_id else item for item in data.actions]
        self._save(data)
        try:
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
            ), on_event=lambda event: self.append_agent_event(run_id, event), cancel_event=cancel_event)
        except Exception as exc:
            result = AgentRunResult(status="failed", summary=f"Agent worker failed: {exc}", events=[{"type": "error", "message": f"Agent worker failed: {exc}", "createdAt": utc_now()}])
        patch_summary = None
        diff = None
        checks: list[CheckResult] = []
        risk_summary = None
        if result.workspace_path and result.status not in {"cancelled", "failed"}:
            self.append_agent_event(run_id, {"type": "checks_started", "message": "Running required checks against the prepared workspace."})
            patch_summary, diff, raw_checks, risk_summary = inspect_workspace(Path(result.workspace_path), repository.requiredChecks if repository else None)
            checks = [CheckResult.model_validate(check) for check in raw_checks]
            self.append_agent_event(run_id, {"type": "checks_completed", "message": f"Completed {len(checks)} required check(s)."})
        with self._write_lock:
            data = self._load()
            current = next((item for item in data.agentRuns if item.id == run_id), running)
            final_status = "cancelled" if cancel_event.is_set() else ("patch_ready" if result.status == "awaiting_approval" and patch_summary is not None else result.status)
            final_events = current.events
            if final_status == "patch_ready" and not any(event.type == "patch_ready" for event in final_events):
                final_events = [*final_events, AgentRunEvent(sequence=len(final_events) + 1, type="patch_ready", message="Patch and check results are ready for human approval.", createdAt=utc_now())]
            updated = current.model_copy(update={
                "status": final_status,
                "summary": (f"Patch prepared for review. {patch_summary}" if result.status == "awaiting_approval" and patch_summary else result.summary),
                "backendSessionId": result.backend_session_id,
                "workspacePath": result.workspace_path,
                "baseCommit": result.base_commit,
                "events": final_events,
                "patchSummary": patch_summary,
                "diff": diff,
                "checks": checks,
                "riskSummary": risk_summary,
            })
            data.agentRuns = [updated if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": updated.status, "summary": updated.summary, "workspacePath": updated.workspacePath, "baseCommit": updated.baseCommit, "events": updated.events, "patchSummary": updated.patchSummary, "diff": updated.diff, "checks": updated.checks, "riskSummary": updated.riskSummary}) if item.id == run_id else item for item in data.actions]
            if checks:
                data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="checks", message=f"Required checks completed for {updated.repository}#{updated.pullRequestNumber}.", actionId=updated.id, createdAt=utc_now()))
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=f"Agent run {updated.action} for {updated.repository}#{updated.pullRequestNumber} is {updated.status}.", actionId=updated.id, createdAt=utc_now()))
            self._save(data)
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
            cancelled = run.model_copy(update={
                "status": "cancelled",
                "summary": "Cancellation requested; stopping the worker.",
                "events": [*run.events, AgentRunEvent(sequence=len(run.events) + 1, type="cancel_requested", message="Cancellation requested; stopping the worker.", createdAt=utc_now())],
            })
            data.agentRuns = [cancelled if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"status": cancelled.status, "summary": cancelled.summary, "events": cancelled.events}) if item.id == run_id else item for item in data.actions]
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=f"Cancellation requested for {run.repository}#{run.pullRequestNumber}.", actionId=run.id, createdAt=utc_now()))
            self._save(data)
            return cancelled

    def approve_agent_run(self, run_id: str, reviewer: str = "local user") -> AgentRun:
        with self._write_lock:
            data = self._load()
            run = next((item for item in data.agentRuns if item.id == run_id), None)
            if run is None:
                raise ValueError("Unknown agent run")
            if run.status not in {"patch_ready", "awaiting_approval"}:
                raise ValueError(f"Run is not ready for approval: {run.status}")
            if not run.checks or any(check.status != "passed" for check in run.checks):
                raise ValueError("All required checks must pass before approval")
            approval = ApprovalRecord(id=f"approval-{uuid4().hex[:12]}", runId=run.id, decision="approved", reviewer=reviewer, baseCommit=run.baseCommit, createdAt=utc_now())
            approved = run.model_copy(update={"status": "approved", "approval": approval, "summary": f"Approved by {reviewer}; ready to push."})
            data.agentRuns = [approved if item.id == run_id else item for item in data.agentRuns]
            data.approvals.insert(0, approval)
            data.actions = [item.model_copy(update={"status": approved.status, "summary": approved.summary, "approval": approved.approval}) if item.id == run_id else item for item in data.actions]
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="approval", message=f"Approved agent run for {run.repository}#{run.pullRequestNumber} by {reviewer}.", actionId=run.id, createdAt=approval.createdAt))
            self._save(data)
            return approved

    def push_agent_run(self, run_id: str) -> AgentRun:
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
        push_ref = f"mergeops/{run.id}"
        try:
            workspace = Path(run.workspacePath)
            if run.diff:
                RunWorkspace._git(workspace, "add", "-A")
                if RunWorkspace._git_optional(workspace, "diff", "--cached", "--quiet") is False:
                    RunWorkspace._git(workspace, "commit", "-m", f"MergeOps prepare {run.repository}#{run.pullRequestNumber}")
            RunWorkspace._git(workspace, "push", "origin", f"HEAD:refs/heads/{push_ref}", token=data.githubPrivate.token)
        except Exception as exc:
            data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="push", message=f"Push failed for {run.repository}#{run.pullRequestNumber}: {exc}", actionId=run.id, createdAt=utc_now()))
            self._save(data)
            raise ValueError(f"Push failed: {exc}") from exc
        pushed = run.model_copy(update={"status": "pushed", "pushRef": push_ref, "summary": f"Pushed approved patch to {push_ref}."})
        data.agentRuns = [pushed if item.id == run_id else item for item in data.agentRuns]
        data.actions = [item.model_copy(update={"status": pushed.status, "summary": pushed.summary, "approval": pushed.approval, "pushRef": pushed.pushRef}) if item.id == run_id else item for item in data.actions]
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="push", message=f"Pushed approved run for {run.repository}#{run.pullRequestNumber} to {push_ref}.", actionId=run.id, createdAt=utc_now()))
        self._save(data)
        return pushed

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
            updated = run.model_copy(update={"events": [*run.events, recorded]})
            data.agentRuns = [updated if item.id == run_id else item for item in data.agentRuns]
            data.actions = [item.model_copy(update={"events": updated.events}) if item.id == run_id else item for item in data.actions]
            self._save(data)

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
        data = self._load()
        action = next((item for item in data.actions if item.id == action_id), None)
        if action is None:
            raise ValueError("Unknown action")
        if action.workspacePath:
            workspace = Path(action.workspacePath).resolve()
            root = RunWorkspace.root.resolve()
            if root not in workspace.parents:
                raise ValueError("Action workspace is outside the MergeOps workspace root")
            run_root = workspace.parent
            if run_root.exists():
                import shutil
                shutil.rmtree(run_root)
        data.actions = [item for item in data.actions if item.id != action_id]
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="action_cleared", message=f"Cleared {action.kind} for {action.repository}#{action.pullRequestNumber}.", actionId=action.id, createdAt=utc_now()))
        self._save(data)

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
        payload["github"] = self._public_github(GitHubSettings.model_validate(payload["githubPrivate"])).model_dump(mode="json")
        data = PersistedAppData.model_validate(payload)
        normalized = [self._normalize_pull_request(pull_request, data) for pull_request in data.pullRequests]
        if normalized != data.pullRequests:
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
            agentRuns=data.agentRuns,
            actions=data.actions,
            activity=data.activity,
            approvals=data.approvals,
            github=self._public_github(data.githubPrivate),
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

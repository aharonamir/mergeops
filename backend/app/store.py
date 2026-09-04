from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from .adapters import AgentRunRequest, RunWorkspace, adapter_registry, utc_now
from .fixtures import agent_backends, agent_runs, github_settings, pull_requests, team_members
from .models import ActionRecord, ActivityEvent, AgentRun, AppData, CheckoutResult, CreateTeamMemberRequest, GitHubSettings, GitHubSettingsPublic, PullRequest, RepositoryConfig, TeamMember, UpdateGitHubSettingsRequest, UpdateTeamMemberRequest


class PersistedAppData(AppData):
    githubPrivate: GitHubSettings


class LocalJsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def app_data(self) -> AppData:
        return self._public(self._load())

    def persisted_data(self) -> PersistedAppData:
        return self._load()

    def create_agent_run(self, backend_id: str, pull_request_id: str, action: str) -> AgentRun:
        data = self._load()
        pull_request = next((item for item in data.pullRequests if item.id == pull_request_id), None)
        if pull_request is None:
            raise ValueError("Unknown pull request")
        run_id = f"run-{len(data.agentRuns) + 1}"
        repository = self._repository_config(data, self._pull_request_repository_key(pull_request, data))
        adapter = adapter_registry(
            [(backend.id, backend.endpoint) for backend in data.agentBackends if backend.enabled]
        ).get(backend_id)
        if adapter is None:
            raise ValueError("Unknown agent backend")
        result = adapter.create_run(
            AgentRunRequest(
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
            )
        )

        run = AgentRun(
            id=run_id,
            backendId=backend_id,
            repository=pull_request.repository,
            pullRequestId=pull_request.id,
            pullRequestNumber=pull_request.number,
            action=action,
            status=result.status,
            requester="local user",
            summary=result.summary,
            backendSessionId=result.backend_session_id,
            workspacePath=result.workspace_path,
            baseCommit=result.base_commit,
            createdAt=utc_now(),
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
            workspacePath=run.workspacePath,
            baseCommit=run.baseCommit,
            createdAt=run.createdAt,
        ))
        data.activity.insert(0, ActivityEvent(id=f"activity-{uuid4().hex[:12]}", kind="agent_run", message=f"Agent run {run.action} for {run.repository}#{run.pullRequestNumber} is {run.status}.", actionId=run.id, createdAt=run.createdAt))
        self._save(data)
        return run

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

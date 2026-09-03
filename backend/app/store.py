from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from .fixtures import agent_backends, agent_runs, github_settings, pull_requests, team_members
from .models import AgentRun, AppData, CreateTeamMemberRequest, GitHubSettings, GitHubSettingsPublic, PullRequest, TeamMember, UpdateGitHubSettingsRequest, UpdateTeamMemberRequest


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

        run = AgentRun(
            id=f"run-{len(data.agentRuns) + 1}",
            backendId=backend_id,
            repository=pull_request.repository,
            pullRequestId=pull_request.id,
            pullRequestNumber=pull_request.number,
            action=action,
            status="awaiting_approval",
            requester="local user",
            summary=f"Queued {action.replace('_', ' ')} run. No push will happen until approval.",
            createdAt=datetime.now(timezone.utc).isoformat(),
        )
        data.agentRuns.insert(0, run)
        self._save(data)
        return run

    def create_team_member(self, payload: CreateTeamMemberRequest) -> TeamMember:
        data = self._load()
        member_id = self._unique_member_id(payload.githubUsername or payload.displayName, data.teamMembers)
        member = TeamMember(id=member_id, **payload.model_dump())
        data.teamMembers.append(member)
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
                github=self._public_github(private_github),
                githubPrivate=private_github,
            )
            self._save(data)
            return data

        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if "githubPrivate" not in payload:
            payload["githubPrivate"] = github_settings.model_dump(mode="json")
        payload["github"] = self._public_github(GitHubSettings.model_validate(payload["githubPrivate"])).model_dump(mode="json")
        data = PersistedAppData.model_validate(payload)
        normalized = [self._normalize_owner(pull_request, data) for pull_request in data.pullRequests]
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
            github=self._public_github(data.githubPrivate),
        )

    def _normalize_owner(self, pull_request: PullRequest, data: PersistedAppData) -> PullRequest:
        author = pull_request.author.casefold()
        for member in data.teamMembers:
            identities = [member.githubUsername, *member.gitAliases]
            if any(author == identity.casefold() for identity in identities if identity):
                return pull_request.model_copy(update={"ownerMemberId": member.id})
        if data.githubPrivate.username and author == data.githubPrivate.username.casefold() and len(data.teamMembers) == 1:
            return pull_request.model_copy(update={"ownerMemberId": data.teamMembers[0].id})
        return pull_request.model_copy(update={"ownerMemberId": "unknown"})

    def _public_github(self, settings: GitHubSettings) -> GitHubSettingsPublic:
        return GitHubSettingsPublic(
            accessMode=settings.accessMode,
            hasToken=bool(settings.token),
            username=settings.username,
            repositories=settings.repositories,
            lastSyncedAt=settings.lastSyncedAt,
        )

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

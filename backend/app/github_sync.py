from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import GitHubSettings, GitHubSyncResult, PullRequest, RepositoryConfig, TeamMember
from .store import LocalJsonStore


class GitHubClient:
    def __init__(self, token: str | None) -> None:
        self.token = token

    def get_json(self, path: str, query: dict[str, str | int] | None = None) -> object:
        url = f"https://api.github.com{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "MergeOps-local",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, headers=headers)
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))


def sync_github_pull_requests(store: LocalJsonStore) -> GitHubSyncResult:
    data = store.persisted_data()
    settings = data.githubPrivate
    synced_at = datetime.now(timezone.utc).isoformat()
    errors: list[str] = []
    imported: list[PullRequest] = []

    client = GitHubClient(settings.token)
    enabled_repositories = [repository for repository in settings.repositories if repository.enabled]

    for repository in enabled_repositories:
        try:
            imported.extend(_sync_repository(client, repository, settings, data.teamMembers))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            errors.append(f"{repository.owner}/{repository.name}: {exc}")

    store.replace_pull_requests(imported, synced_at, errors)

    return GitHubSyncResult(
        syncedAt=synced_at,
        repositoriesScanned=len(enabled_repositories),
        pullRequestsImported=len(imported),
        errors=errors,
    )


def _sync_repository(
    client: GitHubClient,
    repository: RepositoryConfig,
    settings: GitHubSettings,
    team_members: list[TeamMember],
) -> list[PullRequest]:
    usernames = {member.githubUsername for member in team_members if member.githubUsername}
    if not usernames and settings.username and len(team_members) == 1:
        usernames.add(settings.username)

    pull_numbers: set[int] = set()
    for username in usernames:
        result = client.get_json(
            "/search/issues",
            {"q": f"repo:{repository.owner}/{repository.name} is:pr author:{username}", "per_page": 100},
        )
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise ValueError("Unexpected GitHub pull search response")
        for item in result["items"]:
            if isinstance(item, dict) and item.get("number") is not None:
                pull_numbers.add(int(item["number"]))

    pull_requests: list[PullRequest] = []
    for number in sorted(pull_numbers, reverse=True):
        detail = client.get_json(f"/repos/{repository.owner}/{repository.name}/pulls/{number}")
        comments = client.get_json(f"/repos/{repository.owner}/{repository.name}/pulls/{number}/comments", {"per_page": 100})
        if not isinstance(detail, dict):
            continue
        comment_count = len(comments) if isinstance(comments, list) else 0
        author = _login(detail.get("user")) or "unknown"
        owner_member_id = _owner_member_id(author, settings.username, team_members)
        state = _state(detail)
        mergeable = _mergeable(detail.get("mergeable"))
        review_state = "review_required" if detail.get("requested_reviewers") else "commented" if comment_count else "approved"

        pull_requests.append(
            PullRequest(
                id=f"{repository.owner}-{repository.name}-{number}",
                repository=repository.name,
                number=number,
                title=str(detail.get("title") or f"PR #{number}"),
                author=author,
                ownerMemberId=owner_member_id,
                sourceBranch=str((detail.get("head") or {}).get("ref") or ""),
                baseBranch=str((detail.get("base") or {}).get("ref") or repository.defaultBranch),
                state=state,
                mergeable=mergeable,
                reviewState=review_state,
                unresolvedCommentCount=comment_count,
                requestedReviewers=[_login(reviewer) for reviewer in detail.get("requested_reviewers", []) if _login(reviewer)],
                checkState="pending",
                linkedIssueIds=[],
                changedFilesCount=int(detail.get("changed_files") or 0),
                ageDays=_age_days(str(detail.get("created_at") or "")),
                summary=str(detail.get("body") or "")[:280] or "No PR description.",
                searchText=f"{detail.get('title', '')} {detail.get('body', '')}",
            )
        )

    return pull_requests


def _login(value: object) -> str | None:
    if isinstance(value, dict) and value.get("login"):
        return str(value["login"])
    return None


def _owner_member_id(author: str, username: str | None, team_members: list[TeamMember]) -> str:
    normalized_author = author.casefold()
    for member in team_members:
        identities = [member.githubUsername, *member.gitAliases]
        if any(normalized_author == identity.casefold() for identity in identities if identity):
            return member.id
    if username and normalized_author == username.casefold() and len(team_members) == 1:
        return team_members[0].id
    return "unknown"


def _state(detail: dict[str, object]) -> str:
    if detail.get("merged_at"):
        return "merged"
    state = detail.get("state")
    return "closed" if state == "closed" else "open"


def _mergeable(value: object) -> str:
    if value is True:
        return "mergeable"
    if value is False:
        return "conflicting"
    return "unknown"


def _age_days(created_at: str) -> int:
    if not created_at:
        return 0
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return max(0, (datetime.now(timezone.utc) - created).days)

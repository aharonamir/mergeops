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

    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "MergeOps-local",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request("https://api.github.com/graphql", data=json.dumps({"query": query, "variables": variables}).encode("utf-8"), headers=headers, method="POST")
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("errors"):
            raise ValueError("GitHub GraphQL error: " + "; ".join(str(error.get("message", error)) for error in payload["errors"] if isinstance(error, dict)))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Unexpected GitHub GraphQL response")
        return data

    def get_review_threads(self, owner: str, name: str, number: int) -> list[dict[str, object]]:
        query = """
        query($owner:String!, $name:String!, $number:Int!, $after:String) {
          repository(owner:$owner, name:$name) {
            pullRequest(number:$number) {
              reviewThreads(first:100, after:$after) {
                nodes {
                  id isResolved isOutdated viewerCanReply path line
                  comments(first:50) { nodes { id body url createdAt path line diffHunk author { login __typename } } }
                }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
        """
        after: str | None = None
        threads: list[dict[str, object]] = []
        while True:
            data = self.graphql(query, {"owner": owner, "name": name, "number": number, "after": after})
            repository = data.get("repository")
            pull_request = repository.get("pullRequest") if isinstance(repository, dict) else None
            connection = pull_request.get("reviewThreads") if isinstance(pull_request, dict) else None
            if not isinstance(connection, dict):
                raise ValueError("GitHub did not return review threads for this pull request")
            for raw in connection.get("nodes", []):
                if not isinstance(raw, dict):
                    continue
                comments = raw.get("comments") if isinstance(raw.get("comments"), dict) else {}
                comment_nodes = comments.get("nodes", []) if isinstance(comments, dict) else []
                first_comment = comment_nodes[0] if comment_nodes and isinstance(comment_nodes[0], dict) else {}
                author = first_comment.get("author") if isinstance(first_comment, dict) and isinstance(first_comment.get("author"), dict) else {}
                normalized_comments = []
                for comment in comment_nodes:
                    if not isinstance(comment, dict):
                        continue
                    comment_author = comment.get("author") if isinstance(comment.get("author"), dict) else {}
                    normalized_comments.append({
                        "id": str(comment.get("id") or ""), "body": _bounded_graphql_text(comment.get("body")),
                        "author": str(comment_author.get("login") or "unknown"), "authorType": _author_type(comment_author),
                        "createdAt": str(comment.get("createdAt") or ""), "url": comment.get("url"),
                    })
                threads.append({
                    "id": str(raw.get("id") or ""), "author": str(author.get("login") or "unknown"), "authorType": _author_type(author),
                    "path": raw.get("path") or first_comment.get("path"), "line": raw.get("line") or first_comment.get("line"), "excerpt": _bounded_graphql_text(first_comment.get("body")),
                    "body": _bounded_graphql_text(first_comment.get("body")), "diffHunk": _bounded_graphql_text(first_comment.get("diffHunk"), 20000),
                    "createdAt": str(first_comment.get("createdAt") or ""), "url": first_comment.get("url"),
                    "isResolved": bool(raw.get("isResolved")), "isOutdated": bool(raw.get("isOutdated")), "viewerCanReply": bool(raw.get("viewerCanReply")),
                    "comments": normalized_comments,
                })
            page_info = connection.get("pageInfo") if isinstance(connection.get("pageInfo"), dict) else {}
            if not page_info.get("hasNextPage"):
                return threads
            after = str(page_info.get("endCursor"))

    def add_thread_reply(self, thread_id: str, body: str) -> dict[str, object]:
        mutation = """
        mutation($threadId:ID!, $body:String!) {
          addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId, body:$body}) {
            comment { id url }
          }
        }
        """
        data = self.graphql(mutation, {"threadId": thread_id, "body": body})
        result = data.get("addPullRequestReviewThreadReply")
        comment = result.get("comment") if isinstance(result, dict) else None
        if not isinstance(comment, dict):
            raise ValueError("GitHub did not return the created reply")
        return {"id": comment.get("id"), "url": comment.get("url")}


def _bounded_graphql_text(value: object, limit: int = 12000) -> str:
    return str(value or "")[:limit]


def _author_type(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    return "bot" if value.get("__typename") in {"Bot", "App"} else "human" if value.get("login") else "unknown"


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
            imported.extend(_sync_repository(client, repository, settings, data.teamMembers, store))
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
    store: LocalJsonStore | None = None,
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
        review_threads: list[dict[str, object]] | None = None
        try:
            review_threads = client.get_review_threads(repository.owner, repository.name, number)
            comment_count = sum(1 for thread in review_threads if not thread.get("isResolved") and not thread.get("isOutdated"))
        except (HTTPError, URLError, TimeoutError, ValueError):
            # Keep the PR import useful when GraphQL is unavailable. A later
            # drawer refresh will retain/cache a stale snapshot explicitly.
            review_threads = None
        author = _login(detail.get("user")) or "unknown"
        owner_member_id = _owner_member_id(author, settings.username, team_members)
        state = _state(detail)
        mergeable = _mergeable(detail.get("mergeable"))
        review_state = "review_required" if detail.get("requested_reviewers") else "commented" if comment_count else "approved"
        check_state = _check_state(client, repository, detail)

        pull_request = PullRequest(
                id=f"{repository.owner}-{repository.name}-{number}",
                repository=repository.name,
                repositoryFullName=f"{repository.owner}/{repository.name}",
                headRepositoryFullName=_head_repository(detail),
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
                checkState=check_state,
                linkedIssueIds=[],
                changedFilesCount=int(detail.get("changed_files") or 0),
                ageDays=_age_days(str(detail.get("created_at") or "")),
                summary=str(detail.get("body") or "")[:280] or "No PR description.",
                searchText=f"{detail.get('title', '')} {detail.get('body', '')}",
            )
        pull_requests.append(pull_request)
        if review_threads is not None and store is not None:
            try:
                store.cache_review_threads(pull_request.id, review_threads)
            except ValueError:
                # The PR is new to this snapshot; replace_pull_requests will
                # persist the dashboard record before the next detail load.
                pass

    return pull_requests


def _login(value: object) -> str | None:
    if isinstance(value, dict) and value.get("login"):
        return str(value["login"])
    return None


def _head_repository(detail: dict[str, object]) -> str | None:
    head = detail.get("head")
    if not isinstance(head, dict):
        return None
    repository = head.get("repo")
    if isinstance(repository, dict) and repository.get("full_name"):
        return str(repository["full_name"])
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


def _check_state(client: GitHubClient, repository: RepositoryConfig, detail: dict[str, object]) -> str:
    labels = detail.get("labels")
    if isinstance(labels, list) and any(
        isinstance(label, dict) and str(label.get("name") or "").casefold() == "ci-failed"
        for label in labels
    ):
        return "failing"
    head = detail.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    if not sha:
        return "not_run"
    try:
        response = client.get_json(
            f"/repos/{repository.owner}/{repository.name}/commits/{sha}/check-runs",
            {"per_page": 100},
        )
    except (HTTPError, URLError, TimeoutError, ValueError):
        return "pending"
    check_runs = response.get("check_runs") if isinstance(response, dict) else None
    if not isinstance(check_runs, list) or not check_runs:
        return "not_run"

    failing_conclusions = {"action_required", "cancelled", "failure", "startup_failure", "stale", "timed_out"}
    has_pending = False
    for check_run in check_runs:
        if not isinstance(check_run, dict):
            continue
        if check_run.get("status") != "completed":
            has_pending = True
            continue
        if str(check_run.get("conclusion") or "").casefold() in failing_conclusions:
            return "failing"
    return "pending" if has_pending else "passing"


def _age_days(created_at: str) -> int:
    if not created_at:
        return 0
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return max(0, (datetime.now(timezone.utc) - created).days)

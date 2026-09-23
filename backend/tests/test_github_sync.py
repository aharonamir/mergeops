from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.github_sync import _check_state, _sync_repository
from app.models import GitHubSettings, RepositoryConfig, TeamMember


class GitHubSyncTest(unittest.TestCase):
    def test_ci_failed_label_overrides_absent_check_runs(self) -> None:
        repository = RepositoryConfig(id="jiuwenswarm", owner="openJiuwen-ai", name="jiuwenswarm")

        class Client:
            def get_json(self, _path: str, _query: object = None) -> object:
                raise AssertionError("A ci-failed label should not require a check-runs request")

        self.assertEqual(_check_state(Client(), repository, {"labels": [{"name": "ci-failed"}]}), "failing")  # type: ignore[arg-type]

    def test_head_check_runs_map_to_dashboard_states(self) -> None:
        repository = RepositoryConfig(id="jiuwenswarm", owner="openJiuwen-ai", name="jiuwenswarm")
        detail = {"head": {"sha": "head-sha"}}

        for check_runs, expected in (
            ([{"status": "completed", "conclusion": "failure"}], "failing"),
            ([{"status": "in_progress", "conclusion": None}], "pending"),
            ([{"status": "completed", "conclusion": "success"}], "passing"),
            ([], "not_run"),
        ):
            class Client:
                def get_json(self, _path: str, _query: object = None) -> object:
                    return {"check_runs": check_runs}

            with self.subTest(expected=expected):
                self.assertEqual(_check_state(Client(), repository, detail), expected)  # type: ignore[arg-type]

    def test_sync_uses_failed_head_check_run_for_check_state(self) -> None:
        class Client:
            def get_json(self, path: str, _query: object = None) -> object:
                if path == "/search/issues":
                    return {"items": [{"number": 5610}]}
                if path.endswith("/pulls/5610"):
                    return {
                        "title": "Failed CI", "user": {"login": "amir"}, "state": "open", "head": {"ref": "feature", "sha": "head-sha"},
                        "base": {"ref": "main"}, "requested_reviewers": [], "created_at": "2026-01-01T00:00:00Z",
                    }
                if path.endswith("/pulls/5610/comments"):
                    return []
                if path.endswith("/commits/head-sha/check-runs"):
                    return {"check_runs": [{"status": "completed", "conclusion": "failure"}]}
                raise AssertionError(path)

            def get_review_threads(self, _owner: str, _name: str, _number: int) -> list[dict[str, object]]:
                return []

        member = TeamMember(id="amir", displayName="Amir", githubUsername="amir", gitAliases=[], emails=[], currentFocus="", responsibilities="", ownedRepos=[], ownedPaths=[], expertiseTags=[], timezone="UTC", availability="active")
        repository = RepositoryConfig(id="jiuwenswarm", owner="openJiuwen-ai", name="jiuwenswarm")
        settings = GitHubSettings(username="amir", repositories=[repository])

        pull_requests = _sync_repository(Client(), repository, settings, [member])  # type: ignore[arg-type]

        self.assertEqual(pull_requests[0].checkState, "failing")

from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters import AgentRunRequest, AgentRunResult, RunWorkspace, SubprocessAgentAdapter
from app.models import AgentBackend, GitHubSettings, GitHubSettingsPublic, PullRequest, RepositoryConfig, TeamMember
from app.store import LocalJsonStore, PersistedAppData


class CapturingAdapter:
    backend_id = "opencode"

    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    def create_run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return AgentRunResult(status="awaiting_approval", summary="captured")


class StoreRepositoryResolutionTest(unittest.TestCase):
    def test_failed_workspace_creation_removes_partial_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            source.mkdir()
            request = AgentRunRequest(
                run_id="run-failed",
                pull_request_id="pr-1",
                repository="owner/service",
                pull_request_number=1,
                action="analyze",
                backend_id="opencode",
                repository_local_path=str(source),
            )
            with patch.object(RunWorkspace, "root", root / "runs"):
                with patch.object(RunWorkspace, "_git", side_effect=[str(source), RuntimeError("clone failed")]):
                    with self.assertRaises(RuntimeError):
                        RunWorkspace.create(request)

            self.assertFalse((root / "runs" / "run-failed").exists())

    def test_run_workspace_is_independent_and_captures_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            source.mkdir()
            self._git(source, "init", "-b", "main")
            self._git(source, "config", "user.email", "test@example.com")
            self._git(source, "config", "user.name", "MergeOps Test")
            (source / "README.md").write_text("original\n", encoding="utf-8")
            self._git(source, "add", "README.md")
            self._git(source, "commit", "-m", "initial")
            expected_commit = self._git(source, "rev-parse", "HEAD").strip()

            request = AgentRunRequest(
                run_id="run-isolated",
                pull_request_id="pr-1",
                repository="owner/service",
                pull_request_number=1,
                action="analyze",
                backend_id="opencode",
                repository_local_path=str(source),
                base_branch="main",
            )
            with patch.object(RunWorkspace, "root", root / "runs"):
                workspace = RunWorkspace.create(request)

            self.assertEqual(workspace.base_commit, expected_commit)
            self.assertEqual((workspace.path / "README.md").read_text(encoding="utf-8"), "original\n")
            (workspace.path / "README.md").write_text("agent change\n", encoding="utf-8")
            self.assertEqual((source / "README.md").read_text(encoding="utf-8"), "original\n")

    def test_subprocess_agent_receives_isolated_workspace_and_scrubbed_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            source.mkdir()
            self._git(source, "init", "-b", "main")
            self._git(source, "config", "user.email", "test@example.com")
            self._git(source, "config", "user.name", "MergeOps Test")
            (source / "README.md").write_text("original\n", encoding="utf-8")
            self._git(source, "add", "README.md")
            self._git(source, "commit", "-m", "initial")
            runner = root / "runner.js"
            runner.write_text(
                "process.stdin.resume(); process.stdin.on('end', () => console.log(JSON.stringify({type: 'final', status: 'awaiting_approval', summary: `${process.cwd()}|${process.env.MERGEOPS_NO_PUSH}|${process.env.HOME}`})));\n",
                encoding="utf-8",
            )
            request = AgentRunRequest(
                run_id="run-subprocess",
                pull_request_id="pr-1",
                repository="owner/service",
                pull_request_number=1,
                action="analyze",
                backend_id="opencode",
                repository_local_path=str(source),
                base_branch="main",
            )
            adapter = SubprocessAgentAdapter("opencode", runner)
            with patch.object(RunWorkspace, "root", root / "runs"):
                result = adapter.create_run(request)

            self.assertEqual(result.status, "awaiting_approval")
            self.assertIsNotNone(result.workspace_path)
            self.assertIn(f"{result.workspace_path}|1|{result.workspace_path}", result.summary)

    def test_agent_run_uses_repository_full_name_for_duplicate_repo_names(self) -> None:
        data = self._data(
            PullRequest(
                id="pr-1",
                repository="service",
                repositoryFullName="owner-b/service",
                number=12,
                title="Fix service",
                author="dev",
                ownerMemberId="dev",
                sourceBranch="feature/service",
                baseBranch="main",
                state="open",
                mergeable="mergeable",
                reviewState="approved",
                unresolvedCommentCount=0,
                requestedReviewers=[],
                checkState="passing",
                linkedIssueIds=[],
                changedFilesCount=1,
                ageDays=1,
                summary="Ready",
                searchText="ready",
            )
        )
        adapter = CapturingAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalJsonStore(Path(tmpdir) / "mergeops.local.json")
            store._save(data)
            with patch("app.store.adapter_registry", return_value={"opencode": adapter}):
                store.create_agent_run("opencode", "pr-1", "analyze")

        self.assertEqual(adapter.requests[0].repository, "owner-b/service")
        self.assertEqual(adapter.requests[0].repository_local_path, "/tmp/owner-b-service")

    def test_legacy_short_repo_name_does_not_select_an_ambiguous_checkout(self) -> None:
        data = self._data(
            PullRequest(
                id="pr-legacy",
                repository="service",
                number=12,
                title="Fix service",
                author="dev",
                ownerMemberId="dev",
                sourceBranch="feature/service",
                baseBranch="main",
                state="open",
                mergeable="mergeable",
                reviewState="approved",
                unresolvedCommentCount=0,
                requestedReviewers=[],
                checkState="passing",
                linkedIssueIds=[],
                changedFilesCount=1,
                ageDays=1,
                summary="Ready",
                searchText="ready",
            )
        )
        adapter = CapturingAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalJsonStore(Path(tmpdir) / "mergeops.local.json")
            store._save(data)
            with patch("app.store.adapter_registry", return_value={"opencode": adapter}):
                store.create_agent_run("opencode", "pr-legacy", "analyze")

        self.assertEqual(adapter.requests[0].repository, "service")
        self.assertIsNone(adapter.requests[0].repository_local_path)

    def _data(self, pull_request: PullRequest) -> PersistedAppData:
        repositories = [
            RepositoryConfig(id="owner-a-service", owner="owner-a", name="service", localPath="/tmp/owner-a-service"),
            RepositoryConfig(id="owner-b-service", owner="owner-b", name="service", localPath="/tmp/owner-b-service"),
        ]
        github = GitHubSettings(accessMode="contributor_token", token=None, username=None, repositories=repositories)
        return PersistedAppData(
            teamMembers=[
                TeamMember(
                    id="dev",
                    displayName="Dev",
                    githubUsername="dev",
                    gitAliases=[],
                    emails=[],
                    currentFocus="",
                    responsibilities="",
                    ownedRepos=[],
                    ownedPaths=[],
                    expertiseTags=[],
                    timezone="UTC",
                    availability="active",
                )
            ],
            pullRequests=[pull_request],
            agentBackends=[
                AgentBackend(
                    id="opencode",
                    displayName="opencode",
                    adapterType="@opencode-ai/sdk",
                    endpoint="local TypeScript runner",
                    defaultModel="team default",
                    enabled=True,
                )
            ],
            agentRuns=[],
            github=GitHubSettingsPublic(
                accessMode=github.accessMode,
                hasToken=False,
                username=github.username,
                repositories=github.repositories,
                lastSyncedAt=github.lastSyncedAt,
            ),
            githubPrivate=github,
        )

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
        return result.stdout


if __name__ == "__main__":
    unittest.main()

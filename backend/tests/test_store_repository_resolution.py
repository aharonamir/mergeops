from __future__ import annotations

import sys
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters import AgentRunRequest, AgentRunResult, RunWorkspace, SubprocessAgentAdapter, inspect_workspace
from app.models import ActionRecord, AgentBackend, AgentRun, AgentRunEvent, ApprovalRecord, CheckResult, GitHubSettings, GitHubSettingsPublic, PullRequest, RepositoryConfig, TeamMember
from app.store import LocalJsonStore, PersistedAppData


class CapturingAdapter:
    backend_id = "opencode"

    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    def create_run(self, request: AgentRunRequest, on_event=None, cancel_event=None) -> AgentRunResult:
        self.requests.append(request)
        event = {"type": "log", "message": "captured event", "createdAt": "2026-01-01T00:00:00+00:00"}
        if on_event:
            on_event(event)
        return AgentRunResult(
            status="awaiting_approval",
            summary="captured",
            events=[event],
        )


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
                "process.stdin.resume(); process.stdin.on('end', () => { console.log(JSON.stringify({type: 'log', message: 'runner started', createdAt: '2026-01-01T00:00:00.000Z'})); console.log(JSON.stringify({type: 'final', status: 'awaiting_approval', summary: `${process.cwd()}|${process.env.MERGEOPS_NO_PUSH}|${process.env.HOME}`})); });\n",
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
            self.assertEqual([event["type"] for event in result.events or []], ["log", "final"])

    def test_subprocess_agent_streams_progress_and_can_be_cancelled(self) -> None:
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
                "process.stdin.resume(); process.stdin.on('end', () => { console.log(JSON.stringify({type: 'log', message: 'workspace inspected'})); setTimeout(() => console.log(JSON.stringify({type: 'final', status: 'awaiting_approval', summary: 'should not arrive'})), 2000); });\n",
                encoding="utf-8",
            )
            request = AgentRunRequest(
                run_id="run-cancelled",
                pull_request_id="pr-1",
                repository="owner/service",
                pull_request_number=1,
                action="analyze",
                backend_id="opencode",
                repository_local_path=str(source),
                base_branch="main",
            )
            cancel_event = threading.Event()
            seen: list[dict[str, object]] = []

            def on_event(event: dict[str, object]) -> None:
                seen.append(event)
                if event.get("type") == "log":
                    cancel_event.set()

            with patch.object(RunWorkspace, "root", root / "runs"):
                result = SubprocessAgentAdapter("opencode", runner).create_run(request, on_event=on_event, cancel_event=cancel_event)

            self.assertEqual(result.status, "cancelled")
            self.assertEqual([event["type"] for event in seen], ["log", "cancelled"])

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
            persisted = store.persisted_data()
            self.assertEqual([event.message for event in persisted.agentRuns[0].events], ["Run queued; waiting for an available worker.", "Worker started; preparing isolated workspace and launching agent.", "captured event"])
            self.assertEqual([event.message for event in persisted.actions[0].events], ["Run queued; waiting for an available worker.", "Worker started; preparing isolated workspace and launching agent.", "captured event"])

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

    def test_approval_requires_persisted_passing_checks(self) -> None:
        data = self._data(
            PullRequest(
                id="pr-approval",
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
        run = AgentRun(
            id="run-approval",
            backendId="opencode",
            repository="service",
            pullRequestId="pr-approval",
            pullRequestNumber=12,
            action="fix_conflicts",
            status="patch_ready",
            requester="test",
            summary="Patch ready",
            baseCommit="abc123",
            events=[AgentRunEvent(sequence=1, type="final", message="ready", createdAt="2026-01-01T00:00:00Z")],
            createdAt="2026-01-01T00:00:00Z",
        )
        data.agentRuns = [run]
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalJsonStore(Path(tmpdir) / "mergeops.local.json")
            store._save(data)
            with self.assertRaises(ValueError):
                store.push_agent_run(run.id)
            with self.assertRaises(ValueError):
                store.approve_agent_run(run.id)
            run.checks = [CheckResult(name="git diff --check", status="passed", summary="ok", startedAt="2026-01-01T00:00:00Z", finishedAt="2026-01-01T00:00:01Z")]
            store._save(data)
            approved = store.approve_agent_run(run.id)

        self.assertEqual(approved.status, "approved")
        self.assertEqual(approved.approval.decision, "approved")

    def test_required_checks_and_approved_push_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            remote = root / "remote.git"
            source.mkdir()
            self._git(source, "init", "-b", "main")
            self._git(source, "config", "user.email", "test@example.com")
            self._git(source, "config", "user.name", "MergeOps Test")
            (source / "README.md").write_text("original\n", encoding="utf-8")
            self._git(source, "add", "README.md")
            self._git(source, "commit", "-m", "initial")
            base_commit = self._git(source, "rev-parse", "HEAD").strip()
            self._git(root, "init", "--bare", str(remote))
            self._git(source, "remote", "add", "origin", str(remote))

            summary, diff, checks, risk = inspect_workspace(source, ["git diff --check", "git status --porcelain"])
            self.assertEqual(summary, "No working-tree patch was produced.")
            self.assertEqual([check["status"] for check in checks], ["passed", "passed"])
            self.assertIn("Low risk", risk)

            workspace = root / "workspace"
            self._git(source, "push", "origin", "main")
            self._git(root, "clone", str(source), str(workspace))
            self._git(workspace, "remote", "set-url", "origin", str(remote))
            self._git(workspace, "config", "user.email", "test@example.com")
            self._git(workspace, "config", "user.name", "MergeOps Test")
            (workspace / "README.md").write_text("approved change\n", encoding="utf-8")
            run = AgentRun(
                id="run-push",
                backendId="opencode",
                repository="owner/service",
                pullRequestId="pr-push",
                pullRequestNumber=12,
                action="fix_conflicts",
                status="approved",
                requester="test",
                summary="Approved patch",
                workspacePath=str(workspace),
                baseCommit=base_commit,
                diff="diff --git a/README.md b/README.md",
                checks=[CheckResult(name="git diff --check", status="passed", summary="ok", startedAt="2026-01-01T00:00:00Z", finishedAt="2026-01-01T00:00:01Z")],
                approval=ApprovalRecord(id="approval-push", runId="run-push", decision="approved", reviewer="test", baseCommit=base_commit, createdAt="2026-01-01T00:00:00Z"),
                createdAt="2026-01-01T00:00:00Z",
            )
            data = self._data(PullRequest(
                id="pr-push", repository="service", repositoryFullName="owner/service", number=12,
                title="Fix service", author="dev", ownerMemberId="dev", sourceBranch="feature/service", baseBranch="main",
                state="open", mergeable="mergeable", reviewState="approved", unresolvedCommentCount=0,
                requestedReviewers=[], checkState="passing", linkedIssueIds=[], changedFilesCount=1, ageDays=1,
                summary="Ready", searchText="ready",
            ))
            data.agentRuns = [run]
            data.actions = [ActionRecord(id=run.id, kind="agent_run", repository=run.repository, pullRequestId=run.pullRequestId, pullRequestNumber=run.pullRequestNumber, action=run.action, status=run.status, summary=run.summary, createdAt=run.createdAt)]
            store = LocalJsonStore(root / "mergeops.local.json")
            store._save(data)

            pushed = store.push_agent_run(run.id)
            self.assertEqual(pushed.status, "pushed")
            self.assertEqual(pushed.pushRef, "mergeops/run-push")
            self.assertEqual(store.persisted_data().actions[0].pushRef, "mergeops/run-push")
            self.assertIn("mergeops/run-push", self._git(remote, "for-each-ref", "--format=%(refname:short)").splitlines())

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

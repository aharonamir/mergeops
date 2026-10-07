# Claude Code integration plan

## Goals

Add Claude Code as an agent backend and validate it in two phases on open, conflicting PR [#6056](https://github.com/openJiuwen-ai/jiuwenswarm/pull/6056):

1. **Review:** run a read-only review in an isolated workspace.
2. **Conflict fix:** rebase and resolve conflicts in an isolated workspace, then inspect the result. Stop before pushing or merging.

Create `feature/claude-review-conflict-6056` from the current `feature/codex-review-conflict-4281` branch. Preserve existing untracked files.

## Implementation

- Replace the Anthropic SDK stub with the installed Claude Code CLI, invoked headlessly with `claude -p`. Use `--safe-mode`, `--no-session-persistence`, and `--output-format stream-json --verbose`. Use the existing claude.ai login through a per-run profile outside the checkout. Check authentication with that exact profile before each run. Do not use `--bare`, since it disables OAuth login. See [headless CLI options](https://code.claude.com/docs/en/headless).
- Use `--permission-mode plan` for review and `--permission-mode auto` for conflict fixing. Parse the CLI startup event and require the requested mode. If authentication fails, Auto mode is unavailable, or the run needs interactive approval, fail the run and retain its workspace for inspection. See [Claude Code permission modes](https://code.claude.com/docs/en/permission-modes).
- Expose only Claude's Bash tool so repository reads and writes stay inside the Bash sandbox. Enable the sandbox explicitly and fail closed if it cannot start or an action can retry outside it. Deny checkout writes during review. During conflict fixing, allow writes only to the isolated checkout and its Git metadata. Protect staged credentials from sandboxed Bash and verify that Git metadata is isolated from the source repository before launching Claude. Confirm the resolved sandbox settings before each run. See [Claude Code sandbox settings](https://code.claude.com/docs/en/sandboxing).
- Preserve MergeOps' timeout, cancellation, Git guard, workspace fingerprint, rebase evidence, and runtime-file cleanup. Allow `anthropic` in the backend's direct review gate. Label the backend “Claude Code” in the UI and add English and Simplified Chinese strings. Keep existing API and run types.

## Success criteria

- **Review:** reaches `review_ready`, returns findings, and leaves the isolated checkout and Git state unchanged.
- **Conflict fix:** completes the rebase with no unresolved files. Compare the changed paths to PR #6056's original diff and inspect the resulting diff for runtime or temporary files.
- **Both phases:** report the expected permission mode, preserve failure details, and make no remote changes.

## Assumptions

- This is a local experiment using the user's authenticated Claude Code CLI account. Auto mode also depends on an eligible model and organization policy.
- The feature branch is based on `feature/codex-review-conflict-4281`.

## Implementation status

- Created branch `feature/claude-review-conflict-6056` from `feature/codex-review-conflict-4281`.
- Implemented the Claude Code CLI adapter, per-run authentication profile, sandbox configuration and checks, direct-review gate, and “Claude Code” labels/translations. Existing API and action types remain unchanged.
- Ran a review and conflict-fix attempt against PR #6056 in separate isolated workspaces. Both stopped before agent work because the copied claude.ai OAuth session was expired and could not refresh. `claude auth status` reported logged in, but a real headless CLI request failed with `OAuth session expired and could not be refreshed`. The conflict-fix did not begin its rebase. No remote changes were made.
- Review run `claude-6056-review_pr-14942cdd` left the checkout unchanged. The original PR paths were the two localization JSON/component files and its localization test.
- Conflict-fix run `claude-6056-fix_conflicts-ef6ac312` retained its workspace and reported the authentication failure along with the base check. No conflict resolution or rebase was performed.
- Re-run both phases after refreshing the Claude CLI login. The isolated workspaces from the failed attempts are under `/tmp/claude-pr-6056-workspaces`.
- Retried both phases on 2026-10-07 after the backend was selected in settings. The runner verified `plan` mode for review and `auto` mode for conflict fixing, with Bash only, but both CLI requests again failed with `OAuth session expired and could not be refreshed`. Latest run IDs: `claude-6056-review_pr-1ceac23a` and `claude-6056-fix_conflicts-a7e32ebd`. Both checkouts are clean and contain only the PR's original four changed paths relative to `origin/develop`; no unresolved files or remote changes.
- Verification: agent-runner type check/build, frontend production build, and backend compile passed. The backend test suite reached `test_sync_does_not_block_health_endpoint` but stalled in this environment; that test also stalled when run by itself, so the full suite has not been verified to completion. `git diff --check` passed before this status update.

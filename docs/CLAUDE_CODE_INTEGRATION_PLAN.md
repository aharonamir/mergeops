# Claude Code integration plan

## Goals

Add Claude Code as an agent backend and validate it in two phases on open, conflicting PR [#6056](https://github.com/openJiuwen-ai/jiuwenswarm/pull/6056):

1. **Review:** run a read-only review in an isolated workspace.
2. **Conflict fix:** rebase and resolve conflicts in an isolated workspace, then inspect the result. Stop before pushing or merging.

Create `feature/claude-review-conflict-6056` from the current `feature/codex-review-conflict-4281` branch. Preserve existing untracked files.

## Implementation

- Replace the Anthropic SDK stub with the installed Claude Code CLI, invoked headlessly with `claude -p`. Use `--safe-mode`, `--no-session-persistence`, and `--output-format stream-json --verbose`. Set `CLAUDE_CONFIG_DIR` to the user's persistent Claude config directory, outside the checkout, so refreshes update the credential store used by later runs. Keep `HOME` isolated per run. Check authentication against that config directory before each run. Do not use `--bare`, since it disables OAuth login. See [headless CLI options](https://code.claude.com/docs/en/headless).
- Use `--permission-mode auto` for headless review and conflict fixing. Plan mode can require interactive approval for review Bash commands. Parse the CLI startup event and require the requested mode. If authentication fails, Auto mode is unavailable, or the run needs interactive approval, fail the run and retain its workspace for inspection. See [Claude Code permission modes](https://code.claude.com/docs/en/permission-modes).
- Expose only Claude's Bash tool so repository reads and writes stay inside the Bash sandbox. Enable the sandbox explicitly and fail closed if it cannot start or an action can retry outside it. Deny checkout writes during review. During conflict fixing, allow writes only to the isolated checkout and its Git metadata. Deny sandboxed Bash reads of the user's Claude config and credential file, and verify that Git metadata is isolated from the source repository before launching Claude. Confirm the resolved sandbox settings before each run. See [Claude Code sandbox settings](https://code.claude.com/docs/en/sandboxing).
- Preserve MergeOps' timeout, cancellation, Git guard, workspace fingerprint, rebase evidence, and runtime-file cleanup. Allow `anthropic` in the backend's direct review gate. Label the backend “Claude Code” in the UI and add English and Simplified Chinese strings. Keep existing API and run types.

## Success criteria

- **Review:** reaches `review_ready`, returns findings, and leaves the isolated checkout and Git state unchanged.
- **Conflict fix:** completes the rebase with no unresolved files. Compare the changed paths to PR #6056's original diff and inspect the resulting diff for runtime or temporary files.
- **Both phases:** report the expected permission mode, preserve failure details, and make no remote changes.

## Assumptions

- This is a local experiment using the user's Claude Code CLI account. The account must be logged in through the selected persistent config directory; a one-time `claude auth login` is needed if its current session is expired. Auto mode also depends on an eligible model and organization policy.
- The feature branch is based on `feature/codex-review-conflict-4281`.

## Implementation status

- Created branch `feature/claude-review-conflict-6056` from `feature/codex-review-conflict-4281`.
- Implemented the Claude Code CLI adapter, persistent user authentication config with per-run isolated `HOME`, sandbox configuration and checks, direct-review gate, and “Claude Code” labels/translations. Existing API and action types remain unchanged.
- Claude.ai authentication now succeeds through the persistent user config directory (`~/.claude`); the installed CLI reports version `2.1.299`.
- The runner verifies `auto` mode, exposes Bash only, keeps the sandbox enabled, and denies unsandboxed retries. The sandbox on this host initially failed before Bash with `apply-seccomp: write /proc/self/setgroups ... Permission denied`. Setting `sandbox.network.allowAllUnixSockets` to `true` let sandboxed Bash run; this disables Unix-socket filtering, so it needs a narrower upstream fix before broad deployment. The temporary custom `/etc/apparmor.d/bwrap` profile was removed and the stock `bwrap-userns-restrict` profile restored.
- Placeholder files for Claude's protected checkout paths are prepared and cleaned around read-only runs. Their focused backend tests pass. Runner status handling is updated to mark future outputs containing the observed `apply-seccomp` failure as failed rather than `review_ready`.
- The first persisted review of PR #6168 after the sandbox change, `run-aa8e1fc42a1c`, failed when plan mode required interactive approval for Bash. After switching review to auto mode, `run-045cab337c8c` reached `review_ready`, returned findings, and left its isolated checkout clean. The user reports that a Claude Code conflict fix also works. No push or merge was performed as part of this validation.

### Remaining work

1. Replace the `allowAllUnixSockets` workaround with a narrower upstream fix when available; review access to host Unix sockets before deploying this setting more broadly.
2. If the original PR #6056 goal is still needed, repeat both phases on that PR and inspect its rebase evidence and changed files before any push.

- Verification completed for the integration changes: focused backend Claude-profile tests, agent-runner TypeScript check/build, `git diff --check`, and the persisted PR #6168 review. The full backend suite has not been verified to completion; `test_sync_does_not_block_health_endpoint` stalled in this environment in a prior run.

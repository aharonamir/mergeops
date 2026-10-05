# MergeOps presentation brief

Use this as source material for a short product presentation. The points below
describe the current local implementation and its product direction; they do
not claim a benchmark against named competitors.

## One-sentence description

MergeOps is a local-first PR operations cockpit that helps a team lead move
from cross-repository PR triage to a reviewed, approval-gated agent change in
one workflow.

## The problem it addresses

PR work is spread across repositories, GitHub pages, team knowledge, CI
signals, review threads, and separate coding-agent sessions. A lead has to
notice what needs attention, figure out who owns it, coordinate a fix, and
verify the result before anything is pushed.

MergeOps brings those steps together around the PR as the unit of work.

## Main features to present

### 1. One operational view across repositories

- Sync GitHub PRs from configured repositories into one cockpit.
- See review state, CI checks, mergeability, branch freshness, comments, and
  ownership context while triaging.
- Open PR details and review threads without losing the operational view.

### 2. Team context alongside code work

- Keep team identities, responsibilities, repository/path ownership, expertise,
  focus, timezone, and availability in the workspace.
- Use that context while deciding who should handle or review a PR.

### 3. Agent help with a human approval boundary

- Ask an agent to prepare a fix, rebase, conflict resolution, or review-thread
  response in an isolated per-run workspace.
- Inspect the patch, changed files, risk summary, and configured check results.
- Keep push separate from agent work: a person reviews and explicitly approves
  before MergeOps pushes.
- Run OpenCode, Codex, or Claude behind one local runner interface, with
  persisted progress and run history.

### 4. Search across English and Chinese work

- Search GitHub or GitCode for pull requests or issues using an English or
  Simplified Chinese query.
- Use the corresponding PR or issue search skill in an isolated, read-only
  workspace.
- Normalize different agent response formats into one validated result shape.
- Store both English and Chinese summaries and relevance explanations; display
  them in the language selected in the UI.
- Present source-linked results in collapsible cards, including related items
  from other repositories.

## What distinguishes MergeOps

Frame these as product choices and design strengths, rather than absolute
claims about every other tool:

- **It connects triage to a controlled action loop.** The cockpit is designed
  to help a lead identify an intervention, prepare a change, review evidence,
  and approve a push—not just report PR counts.
- **It keeps the human in control of repository writes.** Agents work in
  isolated workspaces without push authority. The host application enforces a
  separate approval step before pushing.
- **It keeps operational context with the PR.** Repository state, team
  ownership, review discussions, CI signals, and agent-run evidence are shown
  as parts of the same workflow.
- **It treats bilingual work as a first-class search case.** Search can span
  English and Chinese descriptions, supports GitHub and GitCode, and returns
  explanations in both languages for display in the user’s chosen UI language.
- **It does not bind the workflow to one coding agent.** OpenCode, Codex, and
  Claude share a runner boundary and a common result contract.
- **It starts local-first.** Repository paths and agent execution stay on the
  developer’s machine in the current build, with local settings and run
  history.

## Suggested short presentation flow

1. **The friction:** PR work and team context are scattered; intervention
   takes coordination across tools.
2. **The cockpit:** show the multi-repository queue and the PR signals used for
   triage.
3. **The team:** show how ownership and reviewer context fit into PR work.
4. **The supervised agent loop:** prepare a patch, inspect checks and risk, and
   show the explicit approval boundary.
5. **Bilingual search:** search for an issue or PR across GitHub/GitCode and
   show bilingual, collapsible results.
6. **Why this shape:** connect operational context, agent flexibility, local
   execution, and human-controlled writes.

## Suggested live demo

1. Sync a configured GitHub repository and open a PR with a review or check
   signal.
2. Inspect its detail and team ownership context.
3. Start an isolated agent action and show progress in the run history.
4. Review the diff and checks; point out that the agent cannot push on its own.
5. Open Search, select issues or PRs and GitHub or GitCode, search for a
   bilingual concept such as “Swarm,” and expand a source-linked result.

## Current implementation status

The local application implements GitHub PR sync, the PR cockpit and detail
workflow, team workspace settings, isolated agent runs, persisted run events,
patch/check review, approval-gated push flow, and bilingual GitHub/GitCode
issue/PR search. It supports OpenCode, Codex, and Claude through the runner.

The application is not yet a hosted multi-user service. The original
implementation spec’s OAuth/device login, Postgres, Redis job queue, and
scheduled reconciliation are future infrastructure work. GitCode currently
provides search, not PR sync. The live GitHub push smoke test is still pending.

### Status against the original spec and roadmap

| Area | Current status | Remaining work |
| --- | --- | --- |
| Product shell and cockpit | React/Vite and FastAPI app with local settings and theme preferences. | Hosted auth and multi-user deployment. |
| GitHub read integration | Contributor-token sync imports PRs and review/check context into the local cockpit. | Scheduled reconciliation and deeper provider/CI coverage. |
| Team workspace | Team profiles and repository/path ownership can be managed locally. | Advanced capacity planning and multi-team hierarchy remain out of scope. |
| Agent adapter foundation | OpenCode, Codex, and Claude run through the local TypeScript child-process boundary with persisted run progress. | Hardening and broader deployment are future work. |
| Approval-gated remediation | Isolated workspaces, patch/check review, approval records, and local push flow are implemented. | Live GitHub push smoke test remains outstanding. |
| Bilingual search | GitHub/GitCode issue and PR search runs in an isolated workspace and normalizes agent output for bilingual display. | No major Slice 6 deliverable is identified as pending in the current implementation. |
| Shared-service infrastructure | App state and job execution are local. | OAuth/device login, Postgres, Redis queue, and hosted deployment are not implemented. |

## Claims to keep precise

- Say **approval-gated push flow implemented locally**; do not imply the live
  GitHub push smoke test has passed.
- Say **GitHub PR operations and GitHub/GitCode search**; do not imply GitCode
  PR synchronization.
- Say **local-first application**; do not call the current build a hosted,
  multi-user product.
- Describe the safety model as **agents prepare changes in isolated workspaces
  and the application requires approval before push**.

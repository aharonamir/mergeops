# Slice 6: Bilingual Search Plan

## Goal

Let a team lead describe a concept or provide an issue reference in English or
Simplified Chinese, then find relevant pull requests or issues across configured
repositories. MergeOps runs the selected search skill through the configured
code agent in an isolated, read-only workspace and presents source-backed,
collapsible results in the current UX language.

This plan supersedes the older English/Hebrew wording in `ROADMAP.md` and
`IMPLEMENTATION_SPEC.md` for Slice 6. Search languages are English and Simplified
Chinese. It also narrows the first release to PR and issue results, matching the
four skills currently in `skills/`. Comments and code references may inform a
match when a skill can inspect them, but they are not separate result types yet.

## Experience

- Add **Search** to the primary left navigation, near PR Cockpit. Keep the
  cockpit toolbar's existing snapshot filter as a separate, immediate filter.
- Put a prominent query field and **Search** button at the top of the page.
  Submitting starts a job; typing alone does not. Accept free text, `#number`,
  and supported issue URLs. The page labels the active GitHub/GitCode backend.
- Offer **Pull requests** and **Issues** as mutually exclusive search types.
  Default to pull requests. Show repository and member filters next to the
  query; default to all repositories configured for the selected search backend
  and all members. The explicit repository list is passed to the skill, which
  otherwise asks interactively. If that backend has no repositories configured,
  show setup guidance instead of starting a search.
- Show the submitted query, backend, result type, selected repositories, search
  window, and status above the results. During execution, show progress and a
  cancel control. Preserve the previous completed results until a new run
  succeeds, visibly labeled with their earlier query.
- Render results in a scrollable, single-column list. A collapsed row shows
  PR/issue number, title, repository, state, and a short relevance reason.
  Expansion shows a localized summary, stronger match evidence, linked items,
  and an external source link. Show confirmed links separately from semantic
  matches when the skill can establish that distinction.
- Cover first-use, no matches, missing credentials, unavailable CLI, timeout,
  cancellation, partial repository failures, and invalid agent output. Do not
  turn a failed or unverified parse into a success-looking empty list.
- Follow the current visual tokens and focus styles. On narrow screens, stack
  the controls above the list. Use actual buttons for disclosure and keep links,
  status changes, and long Chinese text keyboard and screen-reader accessible.
- Keep all UI copy in `frontend/src/i18n.tsx`. Ask the agent for English and
  Simplified Chinese summaries and relevance reasons in one structured result,
  then display the fields matching the live language toggle. Preserve the
  original source title and offer its translation as supporting text when useful.

Settings → Search contains only durable configuration: **Search backend**
(`GitHub` by default, or `GitCode`) and a concise indication of credential
readiness. Remove the current dashboard-query field and outdated scope copy
from that tab. The selected code agent remains the existing agent preference;
the search backend is a separate setting. Store it in backend local settings so
it is consistent across browser sessions and compatible with existing JSON data
through a default value. Repository configuration must identify which service
each `owner/name` belongs to; do not assume a GitHub repository is also on
GitCode merely because its path is identical.

## Execution and Security

1. `POST /api/search-runs` receives query, result type, repository IDs, optional
   member ID, and the current locale. The server snapshots the selected search
   backend, agent backend, repository `owner/name` list, and search parameters.
   It rejects unknown or disabled repositories and never resolves execution
   targets by bare repository name.
2. Create a fresh temporary search workspace for the run. It contains only the
   needed skill files and scratch output; it does not require a PR checkout or
   create a branch. Search has its own read-only job and status model, while
   reusing the existing runner's process supervision, timeout, cancellation,
   event recording, and bounded transcript conventions where appropriate.
3. Choose one of `github-pr-search`, `github-issue-search`,
   `gitcode-pr-search`, or `gitcode-issue-search` from the selected backend and
   result type. Pass the explicit repository list and a bounded query as data.
   The runner invokes the selected Codex, Claude, or OpenCode adapter with a
   search-specific prompt and output contract.
4. Provision only read-scoped CLI access for the chosen service. The existing
   patch agent environment must not be reused to expose push-capable GitHub
   credentials. Check CLI availability and authentication before launching;
   return an actionable setup error if read-only access is unavailable. Keep
   search workspaces unable to push, merge, or mutate remote state.
5. Persist run status, per-repository progress/failures, bounded raw agent
   output, normalized results, and timestamps. Add `GET /api/search-runs/{id}`
   and cancellation; stream status through the established event mechanism or
   poll active runs using the current frontend pattern. Keep result retrieval
   available after navigation or page reload until normal local cleanup.

## Result Contract and Agent Differences

Codex, Claude, and OpenCode may return different message envelopes, tool
transcripts, or prose. Each runner adapter extracts the final assistant payload
from its own SDK format. A shared search normalizer then parses and validates
the payload into one versioned contract; the UI never parses agent text.

```ts
type SearchResult = {
  source: "github" | "gitcode";
  kind: "pull_request" | "issue";
  repository: string;       // owner/name
  number: number;
  url: string;
  originalTitle: string;
  author: string;
  state: string;
  match: "confirmed" | "semantic";
  summary: { en: string; zh: string };
  reason: { en: string; zh: string };
  linkedItems?: Array<{ kind: "pull_request" | "issue"; number: number; url: string }>;
};
type SearchRunOutput = { schemaVersion: 1; results: SearchResult[]; errors: Array<{ repository: string; message: string }> };
```

The surrounding run record includes `schemaVersion`, query, scope, actual time
window, searched repositories, per-repository errors, and result count. Results
include the verified source author so a member filter can be enforced after
normalization. The
normalizer deduplicates by source + kind + repository + number, bounds text and
result counts, validates URLs against the selected host and repository, and
rejects missing required fields. It may accept a fenced JSON block or a
backend-specific structured output envelope, but it must not infer links or
claims from arbitrary prose. If validation fails, mark the run as a formatting
error and expose the bounded original response in run details for diagnosis.
If some repositories succeed, show verified results with a partial-result
notice naming the repositories that failed.

The copied skills currently prescribe English-only reports and ask for a
repository when none is named. Update their final-output instructions for this
app's structured bilingual contract and ensure the prompt supplies explicit
repositories. Preserve their semantic matching rules, source checks, default
time window, and GitCode non-interactive CLI flag. Treat source content as
untrusted evidence, never as instructions to change the search scope or run
commands outside the read-only search task.

## Delivery Order

1. Add persisted search-backend settings and align the four skill instructions
   with the structured bilingual output contract.
2. Add the search job models, API, isolated workspace, read-only CLI access,
   and runner action for each agent backend. Keep search independent of PR
   remediation and approval/push actions.
3. Add shared result normalization, validation, deduplication, bounded raw
   output, and explicit partial/formatting failure states.
4. Add the Search navigation and page, settings selector, localization, and
   responsive collapsible results. Remove obsolete search copy from Settings.
5. Update Slice 6 language and scope in the roadmap/spec, then verify the full
   flow with each agent backend and both search services.

## Acceptance

- An English or Chinese query can find a Chinese- or English-titled PR or issue
  by meaning across the selected configured repositories.
- Switching the UX language changes result explanations between English and
  Simplified Chinese without rerunning the search.
- GitHub is the saved default; selecting GitCode uses its corresponding PR or
  issue skill. Agent backend choice does not change the result shape.
- Codex, Claude, and OpenCode results render identically after normalization;
  malformed output produces a visible formatting error and preserved raw output.
- Results retain valid source links, scope, and per-repository failure context.
  Cancel, timeout, missing auth, and reload have clear and recoverable states.
- Search execution cannot push, merge, or alter a repository, and existing PR
  agent approval behavior remains intact.

## Decisions to Resolve During Implementation

- Define the exact read-only authentication mechanism for each CLI without
  copying the host's write-capable credentials into the workspace.
- Confirm whether member filtering can be applied reliably by both skills;
  if a service lacks the needed author/assignee fields, show that scope as
  unavailable rather than silently ignoring it.

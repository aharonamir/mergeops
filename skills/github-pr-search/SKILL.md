---
name: github-pr-search
description: Search pull requests across GitHub repos and report which ones relate to a given issue number/URL or free-text concept, using the GitHub CLI (gh). Use when the user asks which PRs implement/fix an issue or a concept on github.com repos (e.g. openJiuwen-ai/agent-core), or wants a PR sweep/audit on GitHub.
allowed-tools: Bash(gh*)
---

# GitHub PR ↔ concept search

Find which pull requests in one or more GitHub repos relate to an issue or a
free-text concept the user describes. Uses the `gh` CLI (GitHub CLI). gh is
non-interactive by default when run from a script, so no extra flags are needed.

## Prerequisites — check first, every run

1. Binary on PATH: `gh --version`. If missing, stop and tell the user.
2. Auth: `gh auth status` must show `✓ Logged in to github.com account <user>`.
   If it does not, tell the user to run `gh auth login` themselves in their own
   terminal — do not ask them to paste a token into the conversation.
3. Cheap sanity call that also validates read access to the target repo:
   ```bash
   gh pr list -R <owner>/<repo> --state merged --limit 1
   ```

## Repo selection — ask unless named

Scan **only** the repo(s) the user names. Detect it as a flag (`--repo
<owner>/<repo>`), a natural-language repo name ("agent-core"), or a
`github.com/<owner>/<repo>/...` URL in their input. A local checkout's `origin`
remote is a reasonable default candidate to offer when the user is working in
one.

If the prompt does **not** name a repository, **ask the user which repo to
scan** before running the sweep (offer candidates, e.g. the origin of the
current directory). Do not silently default to a fixed repo list.

## PR state filter

The user can restrict the sweep to one or more PR states: `open`, `closed`,
`merged`, or `all` (default `all` if they don't say). Recognize it either as an
explicit word/combination in their request ("only open PRs", "just merged
ones", "open and merged", "closed or merged") or via `--state=<value>` /
`--state=<value>,<value>` if they pass it flag-style.

Note: on GitHub, `closed` PRs include merged ones; use `merged` for merged only.

`gh pr list --state` only accepts a single enum value
(`open`/`closed`/`merged`/`all`) — it errors on a comma-separated value like
`"open,merged"`. So when the user names more than one state that isn't just
`all`, run the Step 2b sweep once per requested state (each with its own
history-limit cutoff) and merge the results, deduping by PR number, before
Step 3. When they name exactly one state, or say `all`, a single sweep is
enough. Note the chosen state(s) in the final report so the user knows what was
and wasn't searched.

## History limit (days)

**Default: last 60 days.** The user can override with "last 30 days", "past 2
weeks", "since 2026-08-01", or `--days=N`. Convert a stated date to a day count
from today; convert "N weeks"/"N months" to days (7×N / 30×N).

This filters on `updatedAt` (the field the sweep is sorted by), not `createdAt`
— an old PR that was recently touched still counts as within the window, which
is what makes the truncation below possible. Compute the cutoff once
(`today - N days`) before Step 2b.

## Step 1 — classify the input

The user gives either:
- **An issue reference**: a bare number, `#123`, or a `github.com/<owner>/<repo>/issues/<n>` URL.
- **A free-text concept**: a description like "streaming token usage" or "fix
  the race condition in prompt caching".

Strip any repo, state filter, and history limit out of this before classifying
— they're modifiers on the search, not part of the issue reference or concept
text.

## Step 2a — issue reference path

For the (or each) target repo:

```bash
gh issue view <N> -R <owner>/<repo> \
  --json number,title,body,url,closedByPullRequestsReferences
```

`closedByPullRequestsReferences` returns PRs GitHub has formally linked to the
issue — report these as **confirmed** matches. Then still run Step 2b's sweep,
because PRs that mention the issue in prose without a formal link, or that
implement the same underlying change in a different repo, won't show up here.
As an extra recall pass you may run a keyword search for prose mentions:

```bash
gh pr list -R <owner>/<repo> --state all --search "#<N>" --limit 50 \
  --json number,title,state,url
```

## Step 2b — full PR sweep (always do this, both paths)

List every PR in the requested state (default `all`) as JSON into a scratchpad
file (e.g. `/tmp/opencode`) instead of dumping huge output into the transcript:

```bash
gh pr list -R <owner>/<repo> --state <state> \
  --search "sort:updated-desc" --limit 1000 \
  --json number,title,body,state,url,updatedAt,labels,closingIssuesReferences \
  > <scratchpad>/prs-<owner>-<repo>-<state>.json
```

gh pages internally up to `--limit`; there is no manual paging loop. 1000 is a
safe ceiling — if the repo has more PRs than that within the window, bump the
limit, or narrow the state and/or window instead. The sweep comes back sorted
newest-first by `updatedAt`; **apply the history-limit truncation while
reading**: ignore every PR whose `updatedAt` predates the cutoff. (Unlike a
paged CLI, gh fetches the full limit in one call, so this is a read-time filter,
not an early fetch stop.)

If more than one state was requested (per the PR state filter section above),
repeat this whole sweep once per state — `<state>` takes exactly one value per
call — then merge the per-state result sets and dedupe by PR number before
Step 3.

Read each JSON file directly (no `jq`/`python` parsing needed — read the file
and reason over it), keeping `number`, `title`, `body`, `state`, `url`,
`updatedAt`, `labels`. For very large sweeps, write a small Python helper that
applies the day cutoff and keyword pre-filter as it goes rather than reasoning
over every entry in the conversation.

## Step 3 — match against the concept

Judge relevance against the issue's title+body (Step 2a) or the user's
free-text concept using your own semantic judgment, not brittle keyword
matching. PR titles and bodies may be in any language (frequently Chinese in
mirrored repos) — read them as-is and judge on meaning, not literal overlap in
either language: a PR titled "重构(symphony): 将 RLAF-P 提示词优化器委托给
agent-core" is clearly about a "prompt optimizer" concept even though nothing
matches character-for-character.

Don't over-fetch: only pull per-PR details for PRs that are plausible
candidates after the title/body pass, not for every PR in the repo:

```bash
gh pr view <PR> -R <owner>/<repo> \
  --json number,title,body,state,url,labels,files
```

## Step 3.5 — resolve each match's linked issue

For every PR that survives Step 3 as a match (not the whole sweep — just the
final list), get its linked issues. The sweep JSON already contains
`closingIssuesReferences` (number + url per linked issue); if the body's
keyword links weren't captured there, re-check authoritatively:

```bash
gh pr view <PR> -R <owner>/<repo> --json closingIssuesReferences,body
```

If a PR has no linked issue, that's fine — just omit the issue line for it in
the report.

## Step 4 — report

When run by MergeOps, return exactly one JSON object and no markdown fences:

```json
{"schemaVersion":1,"results":[{"source":"github","kind":"pull_request","repository":"owner/name","number":42,"url":"https://github.com/owner/name/pull/42","originalTitle":"Source title, unchanged","author":"source-login","state":"open|closed|merged","match":"confirmed|semantic","summary":{"en":"Accurate English summary.","zh":"准确的简体中文摘要。"},"reason":{"en":"Why this PR matches.","zh":"此 PR 相关的原因。"},"linkedItems":[{"kind":"issue","number":12,"url":"https://github.com/owner/name/issues/12"}]}],"errors":[]}
```

Include only verified links and evidence. `confirmed` means a formal issue link;
use `semantic` for meaning-based matches. Provide both English and Simplified
Chinese for summary and reason regardless of the current UI language. Use an
empty `results` array when there are no matches. Include failed repositories in
`errors` as `{repository, message}` entries, while retaining valid results from
successful repositories. Never fabricate a match or link to make the JSON complete.

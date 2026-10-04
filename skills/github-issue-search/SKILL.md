---
name: github-issue-search
description: Search issues across GitHub repos for ones matching a free-text concept, or resolve the issue(s) linked to a given PR, using the GitHub CLI (gh) server-side issue search. Use when the user asks which issues relate to a concept or which issues a PR links to on github.com repos (e.g. openJiuwen-ai/agent-core).
allowed-tools: Bash(gh*)
---

# GitHub issue concept search

Find which issues in one or more GitHub repos relate to a free-text concept, or
resolve the issue(s) formally linked to a given PR. Uses the `gh` CLI —
specifically its server-side full-text `gh search issues` command. Unlike the
companion `github-pr-search` skill (whose `gh pr list` path pages through the
repo), this one leans on the search engine, so it's much cheaper by default.
gh is non-interactive by default when run from a script, so no extra flags are
needed.

Note: `gh search issues` JSON output has no richer-status field. For the issue's
`stateReason` (e.g. `completed` / `not_planned`, surfaced as "closed (not
planned)"), query `gh issue view <N> --json stateReason` — done per matched
issue in Step 3.5 anyway.

## Prerequisites — check first, every run

1. Binary on PATH: `gh --version`. If missing, stop and tell the user.
2. Auth: `gh auth status` must show `✓ Logged in to github.com account <user>`.
   If it does not, tell the user to run `gh auth login` themselves in their own
   terminal — do not ask them to paste a token into the conversation.
3. Cheap sanity call that also validates read access to the target repo:
   ```bash
   gh search issues "bug" --repo <owner>/<repo> --limit 1
   ```

## Repo selection — ask unless named

Scan **only** the repo(s) the user names. Detect it as a flag (`--repo
<owner>/<repo>`), a natural-language repo name ("agent-core", "jiuwenswarm"),
or a `github.com/<owner>/<repo>/...` URL in their input.

If the prompt does **not** name a repository, **ask the user which repo to
scan** before running the search (offer candidates, e.g. the origin of the
current directory). Do not silently default to a fixed repo list.

## State filter

The user can restrict the search to one issue state: `open`, `closed`, or `all`
(default `all` if they don't say). Recognize it as an explicit word ("only open
issues", "closed issues") or via `--state=<value>`.

`gh search issues --state` only accepts `open` or `closed` — there is no `all`
value. Omitting `--state` entirely searches issues in any state, which is how
`all` is implemented — don't pass `--state all`. If the user names more than one
specific state (e.g. "open and closed" — which is just `all`, so this is rarely
needed), run one search per requested state and merge, deduping by issue number.

GitHub issues also carry a second, more granular closure reason
(`stateReason`: `completed`, `not_planned`, `reopened`) layered over the plain
open/closed the `--state` flag filters on. Filtering only ever operates on
open/closed/all, but surface the richer reason in the final report (e.g.
"closed (not planned)") since it's more informative than bare open/closed —
fetch it via Step 3.5.

## History limit (days)

**Default: last 60 days.** The user can override with "last 30 days", "past 2
weeks", "since 2026-08-01", or `--days=N`. Convert a stated date to a day count
from today; convert "N weeks"/"N months" to days (7×N / 30×N). Filters on
`updatedAt`, computed once as a cutoff date before Step 2b. `--days=0` means no
limit — omit the date filter entirely in that case.

Pass the cutoff server-side with `--updated ">=YYYY-MM-DD"` so the search
engine only returns in-window issues — this is the window's analogue of a
paging early-stop and keeps results cheap.

## Step 1 — classify the input

The user gives either:
- **A PR reference**: a bare number, `#123`, or a
  `github.com/<owner>/<repo>/pull/<n>` URL.
- **A free-text concept**: a description like "budget governance" or "A2UI
  channel leak".

Strip any repo, state filter, and history limit out of this before classifying
— they're modifiers on the search, not part of the PR reference or concept
text.

## Step 2a — PR reference path

For the (or each) target repo:

```bash
gh pr view <N> -R <owner>/<repo> \
  --json number,title,body,url,closingIssuesReferences
```

`closingIssuesReferences` returns issues GitHub has formally linked to that PR —
report these as **confirmed** matches. Then still run Step 2b's concept sweep
using the PR's own title (translated to a concept phrase) as the query, since a
genuinely related issue — a duplicate report, a follow-up filed after the fix —
may exist without a formal link.

## Step 2b — issue search sweep

```bash
gh search issues "<query>" --repo <owner>/<repo> \
  --sort updated --order desc --limit 100 \
  --updated ">=<cutoff-date>" \
  --json number,title,body,state,url,updatedAt,labels,commentsCount \
  > <scratchpad>/issues-<owner>-<repo>-<variant>.json
```

Use a scratchpad directory such as `/tmp/opencode`. Add `--state open` or
`--state closed` only when the state filter calls for it (omit for `all`).
`--limit` caps at **1000** total results for search endpoints; 100 per variant
is plenty in practice. The JSON payload is an array — read the file and reason
over it, keeping `number`, `title`, `body`, `state`, `url`, `updatedAt`,
`labels`, `commentsCount`.

`gh search issues` does lexical search, not semantic search, so a single query
under-counts. Run it once per meaningful query variant: the concept as given,
its most distinctive individual keyword(s), and — since much of this issue
tracker is written in Chinese — a natural Chinese phrasing of the concept if it
wasn't given in Chinese already. Merge and dedupe by issue number across
variants before Step 3. If body matches drown the signal, add `--match title`
(or `--match title,body`) to restrict where the engine looks.

Treat result counts as approximate: the endpoint returns the search engine's
top matches, so exhaustive enumeration of every keyword hit isn't guaranteed —
that's exactly why multiple query variants are run. Because each variant is
sorted by `updated` desc and window-filtered server-side, no client-side cutoff
logic is needed; just read the results.

## Step 3 — match against the concept

Issue titles and bodies are frequently written in Chinese (sometimes mixed with
English, and often using this tracker's structured template with headers like
"问题详细描述" / "版本信息"). Read them as-is and judge relevance on meaning,
not literal keyword overlap — the search sweep already used several query
variants precisely because literal matching under-counts, so apply the same
semantic judgment here that a candidate list built from lexical search still
needs.

For each candidate, judge relevance against the PR's title/body (Step 2a) or
the user's free-text concept using your own semantic judgment. Don't over-fetch:
only pull per-issue details for issues that are plausible candidates after the
title/body pass, not for every result:

```bash
gh issue view <N> -R <owner>/<repo> --json number,title,body,state,url,labels
```

## Step 3.5 — resolve each match's linked PR(s) and status

For every issue that survives Step 3 as a match, check its richer status and
linked PRs in one call:

```bash
gh issue view <N> -R <owner>/<repo> \
  --json stateReason,closedByPullRequestsReferences
```

`closedByPullRequestsReferences` lists the PRs formally linked to the issue
(number + url). Cheap at this point since it's only run per matched issue. If
an issue has no linked PR, omit the line for it in the report rather than
saying "none" — this is also a useful signal on its own (an issue with no
linked PR is likely still unaddressed).

## Step 4 — report

The final answer is always in English, regardless of the source language of any
issue title or body — translate as needed rather than quoting Chinese text
verbatim.

Group by repo. For each match, give exactly:
- **Issue ID** (number, e.g. `#42`)
- **Headline** — the issue title, translated to English if it wasn't already
- **Summary** — a few sentences in English of what the issue actually reports
  or requests, drawn from its body (translated) plus the title, not just a
  restated headline

Also state the issue's status (plain state plus `stateReason` when present,
e.g. "closed (not planned)"), URL, and a one-line reason it matches. When
Step 3.5 found linked PR(s), add their link(s) too (`PR: #<N> — <url>`) — omit
the line entirely for issues with no linked PR. Separate **confirmed**
(formally PR-linked, from Step 2a) from **likely** (semantic match only) when
Step 2a applied. If a repo has zero matches, say so explicitly rather than
omitting it.

Open the report by naming the repo(s), query variant(s), state(s), and history
limit that were actually searched (e.g. "Searched: 'budget governance',
'budget', '预算治理' — open issues only, last 60 days") so the user knows the
scope.

---
name: gitcode-issue-search
description: Search issues across GitCode repos for ones matching a free-text concept, or resolve the issue(s) linked to a given PR, using the gitcode CLI's issue search endpoint. Use when the user asks which issues relate to a concept or which issues a PR links to on GitCode repos such as openJiuwen/agent-core or openJiuwen/jiuwenswarm.
allowed-tools: Bash(gitcode*)
---

# GitCode issue concept search

Find which issues in one or more GitCode repos relate to a free-text concept, or
resolve the issue(s) formally linked to a given PR. Uses the `gitcode` CLI (a
gh-like tool for the GitCode REST API) — specifically its server-side full-text
`search/issues` endpoint. Unlike the companion `gitcode-pr-search` skill (which has
no PR-search endpoint to lean on and must page through the whole repo), this one
leans on the server search, so it's much cheaper by default. **Always run every
`gitcode` invocation non-interactively with the global flag `--no-interactive`**
so the agent never hits an interactive prompt.

Note: the `gitcode search issues` subcommand returns a trimmed JSON payload. For
the full fields the report needs (`updated_at` for the history limit, and
`issue_state_detail` for the richer status), query the raw API endpoint via
`gitcode api 'search/issues?…'` instead — it honors `sort=updated_at&order=desc`
and returns everything.

## Prerequisites — check first, every run

1. Binary on PATH: `gitcode --version`. If missing, stop and tell the user.
2. Auth: `gitcode auth status` must show a logged-in account (e.g.
   `✓ Logged in as <user>`). If it does not, tell the user to run
   `gitcode auth login` themselves in their own terminal — do not ask them to
   paste a token into the conversation. A login done in another process only
   takes effect after that terminal/session is restarted.
3. Cheap sanity call that also validates read access to the target repo:
   ```bash
   gitcode search issues "bug" -R <owner>/<repo> --limit 1 --no-interactive
   ```

## Repo selection — ask unless named

Scan **only** the repo(s) the user names. Detect it as a flag (`--repo
<owner>/<repo>`), a natural-language repo name ("agent-core", "jiuwenswarm"),
or a `gitcode.com/<owner>/<repo>/...` URL in their input.

If the prompt does **not** name a repository, **ask the user which repo to scan**
before running the search (offer the usual candidates, e.g.
`openJiuwen/agent-core` and `openJiuwen/jiuwenswarm`). Do not silently default to
a fixed repo list.

## State filter

The user can restrict the search to one issue state: `open`, `closed`, or `all`
(default `all` if they don't say). Recognize it as an explicit word ("only open
issues", "closed issues") or via `--state=<value>`.

The `search/issues --state` param only accepts a single value. Omitting `--state`
entirely returns issues in any state, which is how `all` is implemented — don't
pass `&state=all`, just leave it out. If the user names more than one specific
state (e.g. "open and closed" — which is just `all`, so this is rarely needed),
run one search per requested state and merge, deduping by issue number.

GitCode issues also carry a second, more granular workflow status
(`issue_state_detail.title`, e.g. `TODO`, `WIP`, `DONE`, `REJECTED`) layered over
the plain open/closed the `state` param filters on. Filtering only ever operates
on open/closed/all, but surface the richer status in the final report (e.g.
"closed (DONE)") since it's more informative than bare open/closed. This field is
only present in the raw API response, not the `gitcode search issues` subcommand
output — another reason to use `gitcode api`.

## History limit (days)

**Default: last 60 days.** The user can override with "last 30 days", "past 2
weeks", "since 2026-08-01", or `--days=N`. Convert a stated date to a day count
from today; convert "N weeks"/"N months" to days (7×N / 30×N). Filters on
`updated_at`, computed once as a cutoff before Step 2b. `--days=0` means no limit.

## Step 1 — classify the input

The user gives either:
- **A PR reference**: a bare number, `#123`, `!123` (GitCode's own PR prefix), or a
  `gitcode.com/<owner>/<repo>/merge_requests/<n>` URL.
- **A free-text concept**: a description like "budget governance" or "A2UI channel leak".

Strip any repo, state filter, and history limit (see above) out of this before
classifying — they're modifiers on the search, not part of the PR reference or
concept text.

## Step 2a — PR reference path

For the (or each) target repo:

```bash
gitcode pr issues <N> -R <owner>/<repo> --no-interactive
```

Returns issues GitCode has formally linked to that PR — report these as
**confirmed** matches. Then still run Step 2b's concept sweep using the PR's own
title (translated to a concept phrase) as the query, since a genuinely related
issue — a duplicate report, a follow-up filed after the fix — may exist without a
formal link.

## Step 2b — issue search sweep

Query the raw API so results come back sorted by `updated_at` desc and carry
`issue_state_detail`:

```bash
gitcode api "search/issues?q=<query>&repo=<owner>/<repo>\
  &sort=updated_at&order=desc&per_page=50&page=1" \
  --no-interactive > <scratchpad>/issues-<owner>-<repo>-p1.json
```

Add `&state=open` or `&state=closed` only when the state filter calls for it
(omit for `all`). `per_page` caps at **50** for this endpoint (it errors
`exceeded limit for per_page` above that). `repo` takes the combined
`owner/repo` form. The JSON payload is an array (or an object whose results sit
under a `data`/`issues` key) — read the file and reason over it, keeping
`number`, `title`, `body`, `state`, `issue_state_detail`, `html_url`,
`updated_at`.

`q` does literal/lexical text search, not semantic search, so a single query
under-counts. Run it once per meaningful query variant: the concept as given, its
most distinctive individual keyword(s), and — since most of this issue tracker is
written in Chinese — a natural Chinese phrasing of the concept if it wasn't given
in Chinese already. Merge and dedupe by issue number across variants before Step 3.

Paginate each variant by increasing `page` while pages keep returning results.
**Apply the history-limit early-stop**: results come back sorted newest-first by
`updated_at`, so as soon as a page's newest issue is older than the cutoff there's
nothing newer to find — stop paging that variant. Drop stale issues (older than
the cutoff) from the final result set. Treat result counts as approximate: the
endpoint returns the search engine's top matches, so exhaustive enumeration of
every keyword hit isn't guaranteed — that's exactly why multiple query variants
are run.

## Step 3 — match against the concept

Issue titles and bodies are frequently written in Chinese (sometimes mixed with
English, and often using this tracker's own structured template with headers like
"问题详细描述" / "版本信息"). Read them as-is and judge relevance on meaning, not
literal keyword overlap — the search sweep already used several query variants
precisely because literal matching under-counts, so apply the same semantic
judgment here that a candidate list built from lexical search still needs.

For each candidate, judge relevance against the PR's title/body (Step 2a) or the
user's free-text concept using your own semantic judgment. Don't over-fetch: only
pull per-issue details (comments, linked PRs) for issues that are plausible
candidates after the title/body pass, not for every result.

## Step 3.5 — resolve each match's linked PR(s)

For every issue that survives Step 3 as a match, check whether it has a linked PR:

```bash
gitcode issue prs <N> -R <owner>/<repo> --no-interactive
```

Cheap at this point since it's only run per matched issue. If an issue has no
linked PR, omit the line for it in the report rather than saying "none" — this is
also a useful signal on its own (an issue with no linked PR is likely still unaddressed).

## Step 4 — report

The final answer is always in English, regardless of the source language of any
issue title or body — translate as needed rather than quoting Chinese text verbatim.

Group by repo. For each match, give exactly:
- **Issue ID** (number, e.g. `#42`)
- **Headline** — the issue title, translated to English if it wasn't already
- **Summary** — a few sentences in English of what the issue actually reports or
  requests, drawn from its body (translated) plus the title, not just a restated headline

Also state the issue's status (plain state plus the richer `issue_state_detail`
when available, e.g. "closed (DONE)"), URL, and a one-line reason it matches. When
Step 3.5 found linked PR(s), add their link(s) too (`PR: !<N> — <url>`) — omit the
line entirely for issues with no linked PR. Separate **confirmed** (formally
PR-linked, from Step 2a) from **likely** (semantic match only) when Step 2a
applied. If a repo has zero matches, say so explicitly rather than omitting it.

Open the report by naming the repo(s), query variant(s), state(s), and history
limit that were actually searched (e.g. "Searched: 'budget governance', 'budget',
'预算治理' — open issues only, last 60 days") so the user knows the scope.

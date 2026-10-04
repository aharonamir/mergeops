---
name: gitcode-pr-search
description: Search pull requests across GitCode repos and report which ones relate to a given issue number/URL or free-text concept, using the gitcode CLI. Use when the user asks which PRs implement/fix an issue or concept on GitCode repos such as openJiuwen/agent-core or openJiuwen/jiuwenswarm.
allowed-tools: Bash(gitcode*)
---

# GitCode PR ↔ concept audit

Find which pull requests in one or more GitCode repos relate to an issue or a
free-text concept the user describes. Uses the `gitcode` CLI (a gh-like tool for
the GitCode REST API). **Always run every `gitcode` invocation non-interactively
with the global flag `--no-interactive`** so the agent never hits an interactive
prompt.

## Prerequisites — check first, every run

1. Binary on PATH: `gitcode --version`. If missing, stop and tell the user.
2. Auth: `gitcode auth status` must show a logged-in account (e.g.
   `✓ Logged in as <user>`). If it does not, tell the user to run
   `gitcode auth login` themselves in their own terminal — do not ask them to
   paste a token into the conversation. A token set in another process only
   takes effect after that process/terminal is restarted.
3. Cheap sanity call that also validates read access to the target repo:
   ```bash
   gitcode pr list -R <owner>/<repo> --state merged --per-page 1 --no-interactive
   ```

## Repo selection — ask unless named

Scan **only** the repo(s) the user names. Detect it as a flag (`--repo
<owner>/<repo>`), a natural-language repo name ("agent-core", "jiuwenswarm"),
or a `gitcode.com/<owner>/<repo>/...` URL in their input.

If the prompt does **not** name a repository, **ask the user which repo to scan**
before running the sweep (offer the usual candidates, e.g. `openJiuwen/agent-core`
and `openJiuwen/jiuwenswarm`). Do not silently default to a fixed repo list.

## PR state filter

The user can restrict the sweep to one or more PR states: `open`, `closed`,
`merged`, or `all` (default `all` if they don't say). Recognize it either as an
explicit word/combination in their request ("only open PRs", "just merged ones",
"open and merged", "closed or merged") or via `--state=<value>` /
`--state=<value>,<value>` if they pass it flag-style.

`gitcode pr list --state` only accepts a single enum value
(`open`/`closed`/`merged`/`all`) — it errors on a comma-separated value like
`"open,merged"`. So when the user names more than one state that isn't just
`all`, run Step 2b's sweep once per requested state (each with its own history-limit
early-stop) and merge the results, deduping by PR number, before Step 3. When they
name exactly one state, or say `all`, a single sweep is enough. Note the chosen
state(s) in the final report so the user knows what was and wasn't searched.

## History limit (days)

**Default: last 60 days.** The user can override with "last 30 days", "past 2
weeks", "since 2026-08-01", or `--days=N`. Convert a stated date to a day count
from today; convert "N weeks"/"N months" to days (7×N / 30×N).

This filters on `updated_at` (the field the sweep is already sorted by), not
`created_at` — an old PR that was recently touched still counts as within the
window, which matches how GitCode's own sort works and is what makes the early-stop
below possible. Compute the cutoff once (`today - N days`) before Step 2b.

## Step 1 — classify the input

The user gives either:
- **An issue reference**: a bare number, `#123`, or a `gitcode.com/<owner>/<repo>/issues/<n>` URL.
- **A free-text concept**: a description like "streaming token usage" or "fix the
  race condition in prompt caching".

Strip any repo, state filter, and history limit (see above) out of this before
classifying — they're modifiers on the search, not part of the issue reference or
concept text.

## Step 2a — issue reference path

For the (or each) target repo:

```bash
gitcode issue view <N> -R <owner>/<repo> --no-interactive
gitcode issue prs <N> -R <owner>/<repo> --no-interactive
```

`issue prs` returns PRs GitCode has formally linked to the issue — report
these as **confirmed** matches. Then still run Step 2b's sweep, because PRs that
mention the issue in prose without a formal link, or that implement the same
underlying change across the *other* repo, won't show up here.

## Step 2b — full PR sweep (always do this, both paths)

List every PR in the requested state (default `all`) writing JSON to a scratchpad
file instead of dumping huge output into the transcript:

```bash
gitcode pr list -R <owner>/<repo> --state <state> \
  --sort updated --direction desc --per-page 100 --page 1 \
  --json --no-interactive > <scratchpad>/prs-<owner>-<repo>-p1.json
```

If more than one state was requested (per the PR state filter section above),
repeat this whole sweep once per state — `<state>` takes exactly one value per
call — then merge the per-state result sets and dedupe by PR number before Step 3.

Increase `--page` and repeat until a page comes back empty (fewer than
`per-page` results, meaning it's the last page). Read each JSON file directly
(no `jq`/`python` parsing needed — read the file and reason over it) and keep just
what's needed for matching: `number`, `title`, `body`/`description`, `state`,
`html_url`, `updated_at`, `labels`.

**Apply the history limit early-stop**: stop paging as soon as a page contains
any PR whose `updated_at` is older than the cutoff — since results come back sorted
newest-first by `updated_at`, everything on later pages is guaranteed to be even
older, so there's nothing left to find. Drop PRs older than the cutoff from that
boundary page before matching, but you don't need to fetch further pages at all.
This is the main lever for keeping a sweep fast: with the default 60-day window
on a repo with thousands of PRs, the sweep usually stops after a few pages instead
of dozens. Note: even with this default window, an `all`-state sweep pages through
everything the window contains; if a run is timing out or taking too long, surface
that narrowing to a single state and/or a smaller `--days=N` window would be much
faster. For a large sweep, write a small Python helper that loops the CLI calls,
applies the day cutoff, and filters by keyword as it goes (as done previously)
rather than fetching every page into the conversation one by one — run it in the
background and keep going once queued.

## Step 3 — match against the concept

PR titles and bodies are frequently written in Chinese (sometimes mixed with
English). Read them as-is — don't skip or deprioritize a PR just because it's in
Chinese — and judge relevance on meaning, not literal keyword overlap in either
language: a PR titled "重构(symphony): 将 RLAF-P 提示词优化器委托给 agent-core" is
clearly about a "prompt optimizer" concept even though nothing matches character-for-character.

For each PR, judge relevance against the issue's title+body (Step 2a) or the user's
free-text concept using your own semantic judgment, not brittle keyword matching.
Consider: title, body, and — if the concept is specific and the sweep leaves real
ambiguity — `gitcode pr view <PR> -R <owner>/<repo> --no-interactive` and
`gitcode pr issues <PR> -R <owner>/<repo> --no-interactive` to check what issues a
candidate PR itself references.

Don't over-fetch: only pull per-PR details (issues list, commits, files) for PRs
that are plausible candidates after the title/body pass, not for every PR in the repo.

## Step 3.5 — resolve each match's linked issue

For every PR that survives Step 3 as a match (not the whole sweep — just the final
list), check whether it has a linked issue and get its URL:

```bash
gitcode pr issues <PR> -R <owner>/<repo> --no-interactive
```

A PR's body sometimes already carries a `Paired:`/linked-issue block (visible in
the raw JSON fetched in Step 2b), but that field was truncated when saved to the
scratchpad file, so don't rely on it alone — the call above is the authoritative
source and cheap at this point since it's only run per matched PR. If a PR has no
linked issue, that's fine — just omit the issue line for it in the report.

## Step 4 — report

The final answer is always in English, regardless of the source language of any PR
title or body — translate as needed rather than quoting Chinese text verbatim.

Group by repo. For each match, give exactly:
- **PR ID** (number, e.g. `#42`)
- **Headline** — the PR title, translated to English if it wasn't already
- **Summary** — a few sentences in English of what the PR actually does, drawn from
  its body/description (translated) plus the title, not just a restated headline

Also state the PR's own state (open/closed/merged), URL, and a one-line reason it
matches. When Step 3.5 found a linked issue, add its link too (`Issue: #<N> —
<url>`; if there are several, list them all) — omit the line entirely for PRs with
no linked issue rather than saying "none". Separate **confirmed** (formally
issue-linked) from **likely** (semantic match only) when Step 2a applied. If a
repo has zero matches, say so explicitly rather than omitting it.

Open the report by naming the repo(s), state(s), and history limit that were
actually searched (e.g. "PR states searched: open, merged — last 60 days" or
"PR states searched: all, no time limit") so the user knows the scope, especially
when it's narrower than the defaults.

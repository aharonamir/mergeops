# issue-concept-search

A Claude Code skill that searches GitCode issues for the two openJiuwen repos and
reports which ones relate to a concept you describe, or which issue(s) a given PR
addresses.

Invoke it with `/issue-concept-search <your input>`.

Companion to the [pr-concept-audit](../pr-concept-audit/README.md) skill — that one
searches PRs and finds their linked issues; this one searches issues and finds
their linked PRs.

## What it does

1. Takes a **free-text concept** ("budget governance", "A2UI channel leak", ...)
   or a **PR reference** (number, `#123`, `!123`, or a
   `gitcode.com/.../merge_requests/N` URL).
2. Searches issues in whichever repo(s) you name (if you don't name one, the
   skill asks which repo to search) using GitCode's real full-text issue search
   API, via the `gitcode` CLI run non-interactively — no need to page through the
   whole repo history like the PR skill does.
3. Judges relevance by meaning, not keyword matching — issue titles/bodies are
   often in Chinese, and the report translates them, it doesn't skip them.
4. For each match, resolves any linked PR and reports:
   - Issue ID
   - Headline (translated to English)
   - English summary of what the issue reports or requests
   - Status (including GitCode's richer workflow state, e.g. "closed (DONE)")
   - URL, and linked PR URL (when one exists)

## Prerequisites

- `gitcode` must be on your PATH.
- You must be logged in via `gitcode auth login` (the CLI reads its stored
  credentials automatically — no need to pass a token in chat). Run `gitcode auth
  status` to check; a login done in another process only takes effect after that
  terminal/session is restarted. (Skip this if you already did it for
  `pr-concept-audit` — it's the same login.)

## Usage

```
/issue-concept-search <free-text concept | PR number | PR URL> [options]
```

Options can be written as flags (`--state=open`) or in plain English ("only open
issues from the last 30 days") — both are recognized.

### Target repo(s)

No fixed default: name a specific repo (or paste a `gitcode.com/...` URL that
includes one) to search only that repo. If the input doesn't name a repo, the
skill asks you which repo to search.

```
/issue-concept-search prompt caching in agent-core
/issue-concept-search --repo openJiuwen/jiuwenswarm budget governance
```

### PR reference input

Instead of a concept, give a PR number/`#N`/`!N`/URL to find the issue(s) that PR
formally closes or references, plus any other issues about the same underlying
problem found via the concept search:

```
/issue-concept-search 2626
/issue-concept-search !2626
/issue-concept-search https://gitcode.com/openJiuwen/agent-core/merge_requests/2626
```

### State filter — `--state=`

Default: `all`.

| Value | Meaning |
|---|---|
| `open` | only open issues |
| `closed` | only closed issues |
| `all` | any state (default) |

```
/issue-concept-search swarmflow budget --state=open
```

Plain-English phrasing also works: "only open issues about X", "closed issues
related to #123".

Note: GitCode issues also carry a more detailed workflow status under the hood
(e.g. `TODO`, `WIP`, `DONE`, `REJECTED`) beyond plain open/closed — filtering only
operates on open/closed/all, but the report shows the detailed status too.

### History limit — `--days=`

Default: **last 60 days**.

Caps the search to issues updated within the last N days.

```
/issue-concept-search swarmflow budget --days=30
/issue-concept-search swarmflow budget --state=open --days=14
```

Pass `--days=0` for no limit (full repo history).

Plain-English phrasing also works: "last 30 days", "past 2 weeks", "since
2026-08-01".

### Combining options

```
/issue-concept-search budget governance --state=closed --days=60
/issue-concept-search 2626
/issue-concept-search only open issues about A2UI in the last month
```

## Output

The report opens by stating exactly what was searched (which query variants,
which state(s), which time window), then lists matches grouped by repo. Each
match includes the issue ID, translated headline, an English summary, its status,
its URL, and — when a PR addresses that issue — the PR's link too.

If you gave a PR reference, matches are split into **confirmed** (issues GitCode
has formally linked to that PR) and **likely** (found only by semantic matching
against the PR's title/body).

## Notes

- Unlike PR search, GitCode issues have a real full-text search endpoint
  (`search/issues`), so this skill doesn't need to sweep the entire repo history
  by default — the default 60-day window keeps it fast.
- The `gitcode search issues` subcommand returns a trimmed payload, so the skill
  queries the raw API via `gitcode api 'search/issues?…'` to get `updated_at`
  sorting and GitCode's richer `issue_state_detail` workflow status.
- Because that search is lexical (matches literal text), not semantic, the skill
  runs your query in a few phrasings — the concept as given, its key terms, and a
  Chinese translation — and merges the results, since most of this tracker is
  written in Chinese. The final relevance judgment is still made by the model, not
  by the raw search hits.
- `per_page` is capped at 50 by this API endpoint (vs. 100 for PR listing).

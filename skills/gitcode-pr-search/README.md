# pr-concept-audit

A Claude Code skill that searches GitCode pull requests for the two openJiuwen
repos and reports which ones relate to an issue or a concept you describe.

Invoke it with `/pr-concept-audit <your input>`.

## What it does

1. Takes an **issue reference** (number, `#123`, or a `gitcode.com/.../issues/N` URL)
   or a **free-text concept** ("prompt optimizer", "budget governance", ...).
2. Sweeps pull requests in whichever repo(s) you name (if you don't name one,
   the skill asks which repo to scan) via the `gitcode` CLI, run
   non-interactively with `--no-interactive`.
3. Judges relevance by meaning, not keyword matching — PR titles/bodies are often
   in Chinese, and the report translates them, it doesn't skip them.
4. For each match, resolves its linked issue (if any) and reports:
   - PR ID
   - Headline (translated to English)
   - English summary of what the PR does
   - State, URL, and linked issue URL (when one exists)

## Prerequisites

- `gitcode` must be on your PATH.
- You must be logged in via `gitcode auth login` (the CLI reads its stored
  credentials automatically — no need to pass a token in chat). Run `gitcode auth
  status` to check; a login done in another process only takes effect after that
  terminal/session is restarted.

## Usage

```
/pr-concept-audit <issue number | issue URL | free-text concept> [options]
```

Options can be written as flags (`--state=open`) or in plain English ("only open
PRs from the last 30 days") — both are recognized.

### Target repo(s)

No fixed default: name a specific repo (or paste a `gitcode.com/...` URL that
includes one) to scan only that repo. If the input doesn't name a repo, the
skill asks you which repo to scan.

```
/pr-concept-audit prompt caching in agent-core
/pr-concept-audit --repo openJiuwen/jiuwenswarm budget governance
```

### PR state filter — `--state=`

Default: `all`.

| Value | Meaning |
|---|---|
| `open` | only open PRs |
| `closed` | only closed (not merged) PRs |
| `merged` | only merged PRs |
| `all` | every state (default) |

Multiple states can be combined with a comma — the underlying API only accepts
one state per call, so the skill runs one sweep per state and merges the results:

```
/pr-concept-audit swarmflows --state=open,merged
/pr-concept-audit swarmflows --state=open
```

Plain-English phrasing works too: "only open PRs about X", "closed or merged PRs
related to #123".

### History limit — `--days=`

Default: **last 60 days**.

Caps the sweep to PRs updated within the last N days. This is the main lever for
speed on these repos (thousands of PRs each) — narrowing the window lets the
sweep stop paging early instead of walking the whole history.

```
/pr-concept-audit swarmflows --days=30
/pr-concept-audit swarmflows --state=open --days=14
```

Pass `--days=0` for no limit (full repo history).

Plain-English phrasing also works: "last 30 days", "past 2 weeks", "since
2026-08-01".

### Combining options

Options can be freely combined, flag-style or in plain English:

```
/pr-concept-audit budget governance --state=merged --days=60
/pr-concept-audit 1728
/pr-concept-audit only closed PRs about A2UI in the last month
```

## Output

The report opens by stating exactly what was searched (which state(s), which
time window), then lists matches grouped by repo. Each match includes the PR ID,
translated headline, an English summary, its state, its URL, and — when GitCode
has a linked issue on that PR — the issue's link too.

If you gave an issue number, matches are split into **confirmed** (PRs GitCode
has formally linked to that issue) and **likely** (found only by semantic
matching against the issue's title/body).

## Notes

- A full `--state=all` sweep with `--days=0` walks the entire PR history of a
  repo (~2,600 in agent-core, ~6,000 in jiuwenswarm as of writing) at roughly one
  API call per 100 PRs (~10s each) — this can take several minutes and may run as
  a background task. The default 60-day window stops early, and narrowing further
  by state and/or `--days` is much faster.
- Matching is done by the model's judgment, not a fixed keyword list, so it
  catches paraphrases and Chinese-language PRs a plain grep would miss.

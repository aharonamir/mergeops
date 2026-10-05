# MergeOps Wishlist

Ideas and product improvements to consider for future implementation. Items are intentionally captured here before being scheduled or broken into implementation tasks.

## PR Cockpit

1. **Add proper Age sorting for pull requests**

   Make the PR Cockpit Age column sort by the actual PR age/date value, with a clear ascending/descending order and consistent handling for missing dates.

## Researched feature opportunities

The order below reflects the current local implementation. Scheduling remains
open.

1. **Explainable intervention queue** — Near term

   Give each PR a priority and a separate next action, each with a short
   explanation. Let the lead override priority while preserving the reason and
   who changed it. Start with signals already available in the cockpit, such
   as checks, reviews, age, ownership, and linked issues. [CodeRabbit's triage
   model](https://docs.coderabbit.ai/triage/prioritization) is a reference for
   keeping priority distinct from blockers.

2. **CI failure workbench** — Near term

   Fetch the relevant failed job logs, identify the failing step and likely
   cause, and attach that evidence when starting an agent fix. Show the source
   log and commit so the diagnosis can be checked. MergeOps already displays
   check state; this would connect it to a specific remediation. References:
   [CodeRabbit CI analysis](https://docs.coderabbit.ai/pr-reviews/cicd-pipeline-analysis)
   and [Qodo CI feedback](https://docs.qodo.ai/qodo-documentation/qodo-merge/tools/tools-list/checks-ci-feedback).

3. **PR readiness summary** — Near term

   Put required checks, unresolved review threads, branch freshness, linked
   issue, patch risk, and approval state into one evidence-backed panel. Mark
   evidence stale when the PR head commit changes, especially before approval
   or push.

4. **Reviewer suggestions from team context** — Next

   Suggest reviewers from changed paths, ownership, expertise, availability,
   and workload. Explain each suggestion and require a person to confirm any
   reviewer assignment. [Linear's triage
   suggestions](https://linear.app/docs/triage-intelligence) are a reference
   for explained routing.

5. **Bilingual relationship and duplicate suggestions** — Next

   Extend search results into suggested issue-to-PR links and likely duplicate
   issues across repositories. Keep the source URL and a bilingual reason for
   every suggestion, and let a person accept or dismiss it. [Linear's
   relationship suggestions](https://linear.app/docs/triage-intelligence) are
   a useful reference.

6. **Compare agent proposals** — Later

   Run two configured agents from the same base commit in separate workspaces,
   then compare their diffs, checks, risk summaries, elapsed time, and cost
   before selecting one proposal. Keep the approval boundary and full run
   history for each candidate. [GitHub's multiple coding-agent
   workflow](https://docs.github.com/en/copilot/concepts/agents/about-third-party-coding-agents)
   shows the growing need to coordinate agent choices.

7. **Cross-repository change impact** — Later

   Show related PRs, dependent changes, affected services, and likely
   collisions across configured repositories. Start with explicit links and
   ownership data before adding inferred impact. References: [CodeRabbit
   multi-repository analysis](https://docs.coderabbit.ai/knowledge-base/multi-repo-analysis)
   and [Graphite's PR workflow](https://graphite.com/docs/get-started).

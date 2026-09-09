# MergeOps Wishlist

Ideas and product improvements to consider for future implementation. Items are intentionally captured here before being scheduled or broken into implementation tasks.

## PR Cockpit

1. **Add proper Age sorting for pull requests**

   Make the PR Cockpit Age column sort by the actual PR age/date value, with a clear ascending/descending order and consistent handling for missing dates.

2. **Save notes for a PR**

   Allow users to add and revisit persistent notes attached to an individual PR. Notes should behave like sticky notes: visible from the PR context and retained between sessions.

3. **Add status-count badges to member cards**

   In the PR Cockpit member cards, show numbered badges for:

   - Conflicts
   - Review / needs review
   - Merged
   - Closed

## Agent Runs

4. **Highlight conflict sections in Ours / Theirs / Result comparisons**

   When a conflict file is shown in a PR Action, highlight the relevant conflict sections and their boundaries in the Ours, Theirs, and Result panes instead of presenting each complete file as an undifferentiated block.

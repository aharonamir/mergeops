# MergeOps Wishlist

Ideas and product improvements to consider for future implementation. Items are intentionally captured here before being scheduled or broken into implementation tasks.

## PR Cockpit

1. **Add proper Age sorting for pull requests**

   Make the PR Cockpit Age column sort by the actual PR age/date value, with a clear ascending/descending order and consistent handling for missing dates.

## Agent Runs

1. **Highlight conflict sections in Ours / Theirs / Result comparisons**

   When a conflict file is shown in a PR Action, highlight the relevant conflict sections and their boundaries in the Ours, Theirs, and Result panes instead of presenting each complete file as an undifferentiated block.

## Biligual search

1. **Bilingual search page: the left pane should show "Seach" which will do a 

   bilingual search in all repositories, it can search on the PRs or it can search on Issue, it will use a skill from the skills folder in the backend, it will create a tmp folder and open the Backend Agent SDK and will send the skill with the search string, it will then wait for a reply and will format the reply

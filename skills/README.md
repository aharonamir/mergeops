# Skills for MergeOps agent runs

Put each OpenCode skill in its own directory here:

```text
skills/
  my-skill/
    SKILL.md
    references/
    scripts/
```

Start `SKILL.md` with YAML frontmatter containing a lowercase, hyphenated `name` matching the directory name and a `description`. For example:

```markdown
---
name: my-skill
description: Use this skill when working on ...
---

Instructions for the agent go here.
```

MergeOps copies this directory into the run's private OpenCode home before starting the agent. OpenCode can then discover the skills automatically and load a relevant one on demand. The copy stays outside the PR checkout at `<run>/.opencode-home/.config/opencode/skills/` and remains there after the run for inspection. Editing a skill affects new runs, including retries, but not one already in progress.

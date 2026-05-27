---
description: Resume work from the most recent .handoff/ entry (append --auto to start executing next steps immediately)
argument-hint: "[--auto]"
allowed-tools: Bash, Read, Glob, Grep
---

Load the latest session handoff and prepare to continue the work.

Most recent handoff:

!`"${CLAUDE_PLUGIN_ROOT}"/scripts/resume.sh`

Then:

- Treat the handoff above as the source of truth for where work stopped.
- Verify the **Repo snapshot** still matches reality: run `git status` and check the
  current branch. Note any drift (new commits, uncommitted changes, branch switch).
- Mode:
  - If the arguments include `--auto` (arguments: `$ARGUMENTS`): give a one-paragraph
    recap, then begin executing the **Next steps** in order, starting with the first
    actionable item.
  - Otherwise: give a short recap (the task, where it stopped, blockers, and the
    proposed next steps) and **ask how to proceed** before changing anything.
- If the snapshot says no handoff exists, tell the user and offer to create one with
  `/session-handoff:save`.

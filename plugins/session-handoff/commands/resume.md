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
- Note **whose** handoff it is. The script labels it either `(this session)` or
  `(another session — verify it matches your task)`:
  - If it is **this session's**, proceed normally per the mode below.
  - If it is **another session's** (or the script listed several to choose from),
    do **not** assume it describes your current task. Give a brief summary, point out
    it came from a different session, and **ask the user to confirm** it's the right
    one (or to name a specific path) before doing anything — even under `--auto`.
- Verify the **Repo snapshot** still matches reality: run `git status` and check the
  current branch. Note any drift (new commits, uncommitted changes, branch switch).
- Mode (applies once the correct handoff is confirmed):
  - If the arguments include `--auto` (arguments: `$ARGUMENTS`) **and** the handoff is
    this session's own: give a one-paragraph recap, then begin executing the
    **Next steps** in order, starting with the first actionable item.
  - Otherwise: give a short recap (the task, where it stopped, blockers, and the
    proposed next steps) and **ask how to proceed** before changing anything.
- If the snapshot says no handoff exists, tell the user and offer to create one with
  `/session-handoff:save`.

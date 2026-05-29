---
description: Resume work from the most recent .handoff/ entry (append --auto to start executing next steps immediately)
argument-hint: "[--auto]"
allowed-tools: Bash, Read, Glob, Grep
---

Load the latest session handoff and prepare to continue the work.

Most recent handoff:

!`"${CLAUDE_PLUGIN_ROOT}"/scripts/resume.sh`

The script output is in one of three shapes. Determine which, then act:

**A. A handoff was loaded** (output starts with `Source:` followed by the handoff
markdown). This is either this session's own handoff `(this session)` or, after a
`/clear` / new session, the single portable handoff `(saved in session …)`. Either is
valid to resume — do **not** treat it as suspicious.
- Verify the **Repo snapshot** still matches reality: run `git status`, check the
  current branch, and note any drift (new commits, uncommitted changes, branch switch).
- If the arguments include `--auto` (arguments: `$ARGUMENTS`): give a one-paragraph
  recap, then begin executing the **Next steps** in order from the first actionable item.
- Otherwise: give a short recap (task, where it stopped, blockers, proposed next steps)
  and **ask how to proceed** before changing anything.

**B. A picker was printed** (output starts with `PICK:` and a numbered list of recent
handoffs). The session has no handoff of its own and there are several to choose from.
- If `--auto`: read the file path shown under **entry 1** (the newest), then proceed as
  in case A's `--auto` branch using that handoff.
- Otherwise: present the numbered list to the user (time · session · summary) and **ask
  which number to resume**. Then read that entry's file path and recap it as in case A.
- Do not execute any next steps until a handoff is chosen.

**C. No handoff exists** (output says none was found). Tell the user and offer to create
one with `/session-handoff:save`.

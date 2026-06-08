---
description: Resume a topic from its latest handoff (survives /clear). Pass a topic/id to target one, or --auto to start executing next steps immediately.
argument-hint: "[--auto] [<id|topic>]"
allowed-tools: Bash, Read, Glob, Grep
---

Load the right session handoff and prepare to continue the work. A **topic** is a thread of
work that spans many sessions (across `/clear`, restarts, and compaction).

Resolution result:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" $ARGUMENTS`

The script output is one of four shapes. Determine which, then act:

**A. A handoff was loaded** (output starts with `Source:` followed by the handoff markdown).
The `(topic: … — …)` tag explains how it was resolved (this session's topic, resumed after
`/clear`, the only recent topic, or your explicit request). The script has already recorded
this topic for the session — it is valid to resume; do **not** treat it as suspicious.
- Verify the **Repo snapshot** still matches reality: run `git status`, check the current
  branch, and note any drift (new commits, uncommitted changes, branch switch).
- If the arguments include `--auto` (arguments: `$ARGUMENTS`): give a one-paragraph recap,
  then begin executing the **Next steps** in order from the first actionable item.
- Otherwise: give a short recap (task, where it stopped, blockers, proposed next steps) and
  **ask how to proceed** before changing anything.

**B. A picker was printed** (output starts with `PICK:` and a numbered list of topics, each
with an `id:`). The session has no topic of its own and several exist — nothing has been
loaded or recorded yet.
- If `--auto`: take **entry 1** (the newest).
- Otherwise: present the numbered list (time · title · summary) and **ask which number to
  resume**.
- Once a choice is made, load it by re-running the command with that entry's id:
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" <id>`
  (this records the topic). Then recap it as in case A. Do not execute any next steps until a topic is chosen.

**C. No handoff exists** (output is `_No handoff found …_`). Tell the user and offer to create
one with `/session-handoff:save`.

**D. The requested id/topic didn't match** (output is `_No handoff matches "…"_`). Tell the
user and suggest `/session-handoff:list --any` to see available topics and ids.

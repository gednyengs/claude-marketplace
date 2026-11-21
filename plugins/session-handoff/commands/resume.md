---
description: Resume a topic from its latest handoff (survives /clear). Pass a topic/id to target one, or --auto to start executing next steps immediately.
argument-hint: "[--auto] [<id|topic>]"
allowed-tools: Bash, Read, Glob, Grep
---

Load the right session handoff and prepare to continue the work. A **topic** is a thread of
work that spans many sessions (across `/clear`, restarts, and compaction).

Arguments passed: `$ARGUMENTS`

Resolution result:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" $ARGUMENTS`

What to do with that output:

!`cat "${CLAUDE_PLUGIN_ROOT}/skills/session-handoff/references/resume-protocol.md"`

If the protocol has you re-run the resolver (a picker choice), use:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" [--auto] <id>
```

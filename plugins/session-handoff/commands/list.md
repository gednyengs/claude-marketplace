---
description: List recent handoffs — the current topic by default, or --any for the latest per topic across the whole project.
argument-hint: "[MAX] [--any]"
allowed-tools: Bash, Read
---

Browse recent handoffs so you can pick one to resume or load. By default this lists handoffs
in the **current topic** (newest first); pass `--any` to list the latest handoff per topic
across the whole project. An optional number caps how many rows are shown (default 5).

Handoffs:

!`"${CLAUDE_PLUGIN_ROOT}"/scripts/list.sh $ARGUMENTS`

Present the list to the user as-is (it is read-only). Remind them they can:
- `/session-handoff:resume <id|topic>` to resume a topic and continue it, or
- `/session-handoff:load <id|topic>` to pull one into context for reference without switching topics.

Each row's `id` (shown as `<topic>/<timestamp>-<session>`) is what those commands accept; a
bare topic slug also works and means "the latest handoff in that topic".

---
name: session-handoff
description: >
  Save or restore working context across Claude Code sessions. Use when the user
  wants to hand off, checkpoint, or preserve the current state of work ("save a
  handoff", "checkpoint where we are", "I'm stopping for the day", "write down where
  we left off"), or to pick work back up ("resume", "where did we leave off", "continue
  from the handoff", "catch me up on this project"). Captures task state, decisions,
  blockers, next steps, and environment commands into version-controlled handoff files,
  grouped by topic so continuity survives /clear, restarts, and compaction.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Session handoff

This skill preserves the "necessary and sufficient" context to resume work later — in a new
session, by a teammate, or after context compaction.

The unit of continuity is a **topic**: a thread of work that spans many sessions. Because
`/clear` starts a brand-new session id, handoffs are keyed on the topic (not the session) so
a workstream stays connected across `/clear`, restarts, and compaction. A session acquires a
topic lazily — the first time you save, resume, or load — and otherwise you rarely name topics
by hand.

Handoffs are markdown files under `.claude/sekekama/session-handoff/handoffs/<topic-slug>/`,
named `YYYY-MM-DD-HHMMSS-<sessionid>.md` so they sort chronologically and never collide
between concurrent sessions. Pre-compaction safety snapshots use a `-auto.md` suffix. Each
file opens with YAML **frontmatter that is the source of truth** (`topic`, `topic_title`,
`session_id`, `created`, `kind`, optional `depends_on`) — the topic subdirectory is just
human-facing organization. Manual handoffs are portable and meant to be committed; auto-snapshots
belong to the session that created them.

There are two equivalent entry points: the `/session-handoff:*` slash commands, and this skill
for when the user asks in natural language. The behavior is the same.

## Saving a handoff

1. Gather a deterministic snapshot: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/snapshot.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}"` —
   git branch, working tree, recent commits, and detected build/test/run commands. Use it as ground truth.
2. Resolve the destination and frontmatter: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/new-path.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" [note] [--topic <slug>]`.
   It prints the exact `PATH`, the resolved `TOPIC`, a **verbatim frontmatter block** (with any
   cross-topic `depends_on` already filled in), and possibly a `NOTICE:`. The topic comes from
   `--topic`, else this session's recorded topic, else a new timestamped topic (pass `--topic` to
   name one). Any note you pass is relayed back as an `ADDITIONAL CONTEXT` block: extra information
   to reflect in the handoff body; it does not name the topic.
3. Write the file to that exact `PATH`, starting with the verbatim frontmatter block (you may
   refine `topic_title`), then the body sections from `templates/HANDOFF_TEMPLATE.md`:
   Task & progress · Key decisions & rationale · Open questions & blockers · Next steps ·
   Environment & commands · Repo snapshot · Resume instructions. Be concise but specific
   (paths, names, exact commands). **Never write secrets, tokens, or credentials.** If an
   `ADDITIONAL CONTEXT` block was printed, fold that user-provided information into the relevant
   section(s), without changing the required sections or the frontmatter.
4. Commit the side effects: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/save-record.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" <PATH> <TOPIC>` — records
   the session's topic, refreshes the per-directory pointer, clears consumed pending state. Run this
   only **after** the file is written; it verifies the handoff at `<PATH>` before recording, so
   pending cross-topic links are never lost on an abort.
5. Report the path, the topic, and a short summary. If `new-path.py` printed a `NOTICE:`, relay
   it — it means a new topic was started while a recently-cleared topic was still resumable.

## Resuming from a handoff

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" [--auto] [<id|topic>]`. Its output is one of four shapes:
   - **A handoff was loaded** (`Source:` … with a `(topic: … — how)` tag): resolved from this
     session's topic, a post-`/clear` baton, the only recent topic, or your explicit id/topic.
     The script has already recorded the topic. Valid to resume — don't treat it as suspicious.
   - **A picker** (`PICK:` + a numbered topic list, each with an `id:`): no topic for this session
     and several exist. Present it and ask which number (or take entry 1 when continuing
     automatically), then load the choice by re-running `resume.py` (as in step 1) with that id.
   - **No handoff found**: tell the user and offer `/session-handoff:save`.
   - **No match** (`_No handoff matches …_`): the requested id/topic didn't resolve; suggest
     `/session-handoff:list --any`.
2. Verify the repo snapshot still matches reality (`git status`, current branch); note drift.
3. Recap the task, where it stopped, blockers, and proposed next steps. Ask before making changes
   unless the user clearly wants you to continue automatically (`--auto` → execute the next steps).

## Loading & listing

- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/load.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" <id|topic>` — pull **any** topic's handoff into context
  for reference *without* changing the session's current topic. If it's a different topic, its id
  is recorded so the next save notes it as a `depends_on`. Summarize what it covers and how it
  relates; don't switch tasks unless asked.
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/list.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" [MAX] [--any]` — list handoffs in the current topic, or
  with `--any` the latest per topic across the project. Read-only; each row's `id` feeds `load`/`resume`.

Ids are `<topic>/<timestamp>-<session>`; a bare topic slug also works and means "the latest handoff
in that topic".

## Automatic safety net (hooks)

The plugin protects context without being asked:
- **PreCompact** writes a deterministic safety snapshot (with `<!-- TODO -->` placeholders) to the
  session's topic before the context window is compacted, and asks you to enrich it — emphasizing
  the **in-flight step** — while you still have full context.
- **SessionStart** is source-aware: `resume` → no-op (the transcript is already restored);
  `compact` → a concise continue-nudge (auto) or light pointer (manual) to the snapshot; `clear` →
  recaps the topic you just cleared (claimed from a per-directory clear-log) and offers to resume,
  or shows a picker if multiple clears are ambiguous; `startup` → a short list of recent topics.
  It never silently adopts a topic or injects another session's content.
- **SessionEnd(clear)** leaves a small "baton" carrying the cleared session's own topic, so the
  next (new) session can pick it back up. No eager deletion — state is reclaimed by an age sweep.
- **Stop** nudges you (at most twice) to finish filling an auto-snapshot's placeholders.

When you see a PreCompact or Stop directive about an unfilled auto-snapshot, open the named
`*-auto.md` file and replace every `<!-- TODO -->` with real content from the conversation.

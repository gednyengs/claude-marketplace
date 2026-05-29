---
name: session-handoff
description: >
  Save or restore working context across Claude Code sessions. Use when the user
  wants to hand off, checkpoint, or preserve the current state of work ("save a
  handoff", "checkpoint where we are", "I'm stopping for the day", "write down where
  we left off"), or to pick work back up ("resume", "where did we leave off", "continue
  from the handoff", "catch me up on this project"). Captures task state, decisions,
  blockers, next steps, and environment commands into version-controlled .handoff/ files.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Session handoff

This skill preserves the "necessary and sufficient" context to resume work later — in a
new session, by a teammate, or after context compaction. Handoffs are markdown files in a
`.handoff/` directory at the project root, named `YYYY-MM-DD-HHMMSS-<sessionid>.md` so they
sort chronologically, form a history, and never collide between concurrent sessions in the
same project. Pre-compaction safety snapshots use a `-auto.md` suffix. Manual handoffs are
portable and meant to be committed with the repo; a teammate or new session can resume any
of them. Auto-snapshots are private to the session that created them.

There are two equivalent entry points: the `/session-handoff:save` and
`/session-handoff:resume` slash commands, and this skill for when the user asks in natural
language. The behavior is the same.

## Saving a handoff

1. Gather a deterministic snapshot by running the bundled script:
   `"${CLAUDE_PLUGIN_ROOT}"/scripts/snapshot.sh`
   It prints the git branch, working-tree status, recent commits, and detected
   build/test/run commands. Use this as factual ground truth.
2. Get the exact target path (already session-tagged, with `.handoff/` created) by running:
   `"${CLAUDE_PLUGIN_ROOT}"/scripts/new-path.sh`
   Write to that exact path — do not invent a filename, since the session tag prevents
   collisions with other concurrent sessions.
3. Write the file using the structure in
   `templates/HANDOFF_TEMPLATE.md` (read it once for the exact headings). Fill every
   section from the conversation:
   - **Task & progress** — goal; done; in progress; not started.
   - **Key decisions & rationale** — choices and *why*.
   - **Open questions & blockers** — unresolved items, waiting-ons, risks.
   - **Next steps** — ordered, actionable checklist.
   - **Environment & commands** — build/test/run, env vars, setup, how to reproduce state.
   - **Repo snapshot** — the git facts from the snapshot script.
   - **Resume instructions** — the first concrete actions for the next session.
4. Be concise but sufficient; prefer specifics (paths, names, exact commands) over vague
   summaries. Never write secrets, tokens, or credentials.
5. Report the path and a short summary of what you captured.

## Resuming from a handoff

1. Read the relevant handoff:
   `"${CLAUDE_PLUGIN_ROOT}"/scripts/resume.sh`. It prints this session's own latest
   handoff when one exists (labeled `(this session)`); otherwise it lists the portable
   manual handoffs from other sessions and shows the newest (labeled accordingly).
2. If the handoff is from **another session**, do not assume it describes the current
   task — summarize it and confirm with the user (or take a specific path) before acting.
3. Verify the repo snapshot still matches reality (`git status`, current branch); note drift.
4. Recap the task, where it stopped, blockers, and proposed next steps. Ask before making
   changes unless the user clearly wants you to continue automatically with this session's
   own handoff.

## Automatic safety net (hooks)

The plugin also protects context without being asked:
- **PreCompact** writes a deterministic safety snapshot (with TODO placeholders) before the
  context window is compacted, and asks you to enrich it while you still have full context.
- **SessionStart** injects the most recent handoff so a new or post-compaction session knows
  where things stood.
- **Stop** nudges you (at most twice) to finish filling an auto-snapshot's placeholders.

When you see a PreCompact or Stop directive about an unfilled auto-snapshot, open the named
`.handoff/*-auto.md` file and replace every `<!-- TODO -->` with real content from the
conversation.

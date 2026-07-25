---
description: Save a session handoff — capture task state, decisions, blockers, next steps, and how to resume. Groups under a topic that survives /clear.
argument-hint: "[note] [--topic <slug>]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

You are writing a **session handoff** so this work can be resumed cleanly later — in a
new session, by a teammate, or after the context window is compacted. Optimize for a
reader with **zero memory** of this conversation.

Deterministic project snapshot (gathered for you just now):

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/snapshot.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}"`

Destination path and the exact frontmatter to use (topic already resolved from
`--topic`, this session's topic, or a new one — and any cross-topic `depends_on`
already computed for you):

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/new-path.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" $ARGUMENTS`

Now do the following:

1. **Write the handoff to the exact `PATH` printed above.** Do not invent a filename —
   the timestamp + session tag prevent collisions between concurrent sessions.
2. **Begin the file with the verbatim frontmatter block** printed above (between its
   `---` fences). You may improve `topic_title` to a concise human title, but keep
   `topic`, `session_id`, `created`, `kind`, and any `depends_on` exactly as given.
3. After the frontmatter, write these sections, filled from THIS conversation. Be concise
   but sufficient — favor specifics (paths, names, command lines, decisions) over generalities:
   - `# Handoff — <human-readable date/time>`
   - `## Task & progress` — the goal; what's done; what's in progress; what's not started.
   - `## Key decisions & rationale` — important choices and *why*, so they aren't relitigated.
   - `## Files & code touched` — the specific files and functions central to this work and why each
     matters, so the next session knows where to look without re-deriving it. Include short,
     load-bearing snippets where a one-line description won't do.
   - `## Approaches tried & dead ends` — OPTIONAL: include this section only if you hit attempts that
     would be expensive or tempting to repeat (what was tried, why it failed or was abandoned). Omit
     the section entirely when there were none.
   - `## Open questions & blockers` — unresolved questions, things waiting on input, known risks.
   - `## Next steps` — an ordered, actionable checklist of what to do next. If you stopped mid-step,
     make item 1 the in-flight action and quote VERBATIM where you left off (the exact edit, command,
     or user request underway) so the next session resumes without drift.
   - `## Environment, commands & results` — how to build/test/run, env vars, and setup. Start from
     the detected commands in the snapshot above and refine them with what you actually ran this
     session. Also record meaningful pass/fail results or measurements, and paths to any data files
     or artifacts the next session needs (JSON, CSV, logs).
   - `## Repo snapshot` — paste the branch / working tree / recent commits from the snapshot above.
   - `## Resume instructions` — the first few concrete actions the next session should take.

   If an `ADDITIONAL CONTEXT` block was printed above (from the save note), treat the user note
   inside it as extra information to reflect in this handoff: it may be a detail or fact to preserve,
   a constraint to record, or something to emphasize. Work it into the relevant section(s), while
   keeping every required section and the frontmatter exactly as specified.
4. Do **not** write secrets, tokens, or credentials into the handoff.
5. **After writing**, run this to record the save (binds the session to the topic and clears
   consumed pending state). Pass the same `PATH` and `TOPIC` printed above — the script verifies
   the file before recording, so use the exact values:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/save-record.py" --project-dir "${CLAUDE_PROJECT_DIR}" --plugin-data "${CLAUDE_PLUGIN_DATA}" <PATH> <TOPIC>
   ```

6. Print the relative path, the topic, and a 3–5 bullet summary of what you captured. **Relay any
   `NOTICE:` line** from either script — from `new-path.py` it means you started a new topic while a
   recently-cleared topic was still resumable; from `save-record.py` it means git ignores the
   handoff location, so these files stay local instead of being shared.

This handoff is meant to be committed with the repo, so write it for your future self and
your teammates.

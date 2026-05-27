---
description: Save a session handoff — capture task state, decisions, blockers, next steps, and how to resume into .handoff/
argument-hint: "[optional note about this checkpoint]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

You are writing a **session handoff** so this work can be resumed cleanly later — in a
new session, by a teammate, or after the context window is compacted. Optimize for a
reader with **zero memory** of this conversation.

Deterministic project snapshot (gathered for you just now):

!`"${CLAUDE_PLUGIN_ROOT}"/scripts/snapshot.sh`

Optional note for this checkpoint: $ARGUMENTS

Now do the following:

1. Determine the project root and ensure a `.handoff/` directory exists there
   (create it if missing).
2. Choose a filename `.handoff/<YYYY-MM-DD-HHMMSS>.md` using the current local time
   (sortable; newest sorts last).
3. Write the file with **exactly** these sections, filled from THIS conversation.
   Be concise but sufficient — favor specifics (paths, names, command lines, decisions)
   over generalities:

   - `# Handoff — <human-readable date/time>`
   - A one-line note if `$ARGUMENTS` was provided.
   - `## Task & progress` — the goal; what's done; what's in progress; what's not started.
   - `## Key decisions & rationale` — important choices and *why*, so they aren't relitigated.
   - `## Open questions & blockers` — unresolved questions, things waiting on input, known risks.
   - `## Next steps` — an ordered, actionable checklist of what to do next.
   - `## Environment & commands` — how to build/test/run, env vars, setup, and how to
     reproduce the current working state. Start from the detected commands in the
     snapshot above and refine them with what you actually used this session.
   - `## Repo snapshot` — paste the branch / working tree / recent commits from the
     snapshot above.
   - `## Resume instructions` — the first few concrete actions the next session should take.

4. Do **not** write secrets, tokens, or credentials into the handoff.
5. After writing, print the relative path and a 3–5 bullet summary of what you captured.

This handoff is meant to be committed with the repo, so write it for your future self
and your teammates.

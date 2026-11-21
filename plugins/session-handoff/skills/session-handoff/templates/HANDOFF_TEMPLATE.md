<!--
HANDOFF TEMPLATE. This file is the single source of truth for what a handoff contains; the
/session-handoff:save command and the skill both follow it.

Everything inside an HTML comment is guidance for you, the writer. Replace it with real content and
never copy a comment into the handoff.

WRITING RULES

- Write for a reader with ZERO memory of this conversation: a fresh session, or a teammate. If they
  would have to guess at something, it is not written down yet.
- Be specific. Real paths, names, exact command lines, and quoted wording beat summaries.
- Say how you know. For a diagnosis, a root cause, or anything listed as in progress, state whether
  it was VERIFIED (name the command or observation that showed it) or is an ASSUMPTION. "The bug is
  in parser.py" reads the same whether it was confirmed or guessed, and the next session will act on
  it either way. Routine facts do not need a label.
- Carry forward. If new-path.py printed a PREVIOUS HANDOFF, this file replaces it as the topic's
  latest, and resume loads only the latest. Bring forward every constraint, decision, dead end,
  lesson, and pending decision that is still in force. Drop what has been resolved or superseded,
  so the handoff describes the present instead of accumulating history.
- Never write secrets, tokens, passwords, or credential values. Refer to them by name or location.
- Sections marked OPTIONAL are left out entirely, heading included, when there is nothing to put in
  them. Every other section is always present.

The file begins with the frontmatter block printed by new-path.py, copied verbatim (you may refine
`topic_title`; change nothing else in it). The body follows.
-->

# Handoff — <YYYY-MM-DD HH:MM:SS TZ>

## Task & progress

<!--
The goal in one or two sentences (the first line is used as the topic's one-line summary), then:
- Done when: the observable condition that means this task is finished (the tests that must pass,
  the behavior to see, the artifact to ship). If the user never said, give your best understanding
  and mark it as an assumption.
- Done: …
- In progress: … (verified or assumed, and how)
- Not started: …
-->

## Constraints & instructions from the user

<!--
Standing rules the user gave that a fresh session must keep obeying: "don't touch the migrations",
"use pnpm", "keep the public API stable", "ask before pushing". Quote the user's wording where the
wording matters. Only what the user said belongs here; your own choices go under Key decisions.
Say where each one comes from: "(this session)" if the user said it in this conversation, or
"(carried from the previous handoff)" if you only know it from a handoff you read. A rule you did
not hear from the user stays marked as carried, however many saves it passes through.
Write "None stated." if there were none.
-->

## Decisions waiting on the user

<!--
OPTIONAL. Questions you put to the user that they have not answered yet. For each one:
- Question: quoted as it was presented, with the options that were offered.
- Recommendation: yours, with the reason. Label it as a recommendation; it is not an answer.
- Blocks: which next steps cannot start until it is answered, and what (if anything) proceeds on a
  default in the meantime.
The next session re-asks these before acting on them. Never record a guess as the user's answer.
-->

## Key decisions & rationale

<!--
The choices that matter and *why*, so they aren't relitigated next session.
- Decision — rationale
-->

## Files & code touched

<!--
The specific files and functions central to this work, and WHY each matters, so the next session
knows where to look without re-deriving it. Start each bullet with the project-relative path in
backticks (resume checks that these still exist). Include short, load-bearing snippets where a
one-line description won't do.
- `path/to/file` — what changed / why it matters
-->

## Approaches tried & dead ends

<!--
OPTIONAL. Attempts that would be expensive or tempting for the next session to repeat: what was
tried and why it failed or was abandoned.
- Tried X -> failed because Y
-->

## Lessons learned

<!--
OPTIONAL. Rules for HOW to work on this from here on, learned from a mistake or a correction in this
session or an earlier one.
- Lesson — what went wrong that taught it
This is distinct from a dead end (an approach not to retry) and from a constraint (something the
user told us). If a lesson would hold beyond this topic, mark it "(candidate for CLAUDE.md)" and
mention it in your save summary so the user can decide where it should live.
-->

## Agents & messages in flight

<!--
OPTIONAL. Work and communication that lives outside this conversation at the moment of saving. A
background subagent keeps running across `/clear` and reports to the session that follows, which
will have no memory of asking for it; it is stopped when Claude Code exits. So record enough for
the next session to recognize a result that arrives, check on the agent, or redo the work.
- Running agent: its name or id · the brief it was given, quoted verbatim so it can be re-spawned ·
  where its output lands (worktree, branch, files, artifact) · its state at save time · what to do
  with the result when it arrives.
- Awaiting a reply: from whom (the session or agent name it is addressed by) · what was asked, and
  when · what the reply unblocks · what to do if it never arrives.
- Unsent message: to whom · the draft, verbatim · why it has not been sent yet. Also list sending
  it under Next steps.
If an `AGENTS RUNNING NOW` block was printed with the destination path, it is Claude Code's own list of
this session's running subagents and teammates: every agent in it gets an entry here, and `none`
means only that this session has none of its own (workflow agents and other sessions are not listed).
If an agent is about to finish, collect its result before saving instead of recording it as in flight.
-->

## Open questions & blockers

<!--
Unknowns nobody has answered yet, external blockers, and known risks. A question that is the
user's to decide goes under "Decisions waiting on the user" instead.
- …
-->

## Next steps

<!--
Start with one or two checks that confirm the state is as described here before anything is changed
(for example: "run `<command>`, expect `<result>`"). Then an ordered, actionable checklist. The first
item should be unambiguous. If you stopped mid-step, make item 1 the in-flight action and include a
VERBATIM quote of where you left off (the exact edit, command, or user request underway) so the next
session resumes without drift. Mark any step that waits on an unanswered decision as blocked on it.
- Confirm first: …
1. …
2. …
-->

## Environment, commands & results

<!--
How to build / test / run, required env vars, and setup. Start from the auto-detected commands and
refine with what you actually ran this session. Record meaningful results with their anchor: the
exact command, its outcome, and the state it ran against (the commit, and whether the tree had
uncommitted changes). For example:
- `pytest tests/test_parser.py::test_utf8` → fails with KeyError, at abc1234 plus uncommitted edits
  to `parser.py`
A result without its command and commit cannot be re-checked. Also give the paths to any data files
or artifacts the next session needs (JSON, CSV, logs).
-->

## Repo snapshot

<!--
The "Repo snapshot" part of snapshot.py's output (branch, working tree, recent commits), pasted
without editing. Its detected commands belong under "Environment, commands & results" above, not here.
-->

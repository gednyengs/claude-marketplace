# Session Handoff

Save and restore your working context across Claude Code sessions. When you stop mid-task, run
`/clear`, switch agents, or hit auto-compaction, you normally lose the expensive part: what you
were doing, the decisions you made and why, what's blocking you, and how to run things. Session
Handoff writes all of that to a file so any later session can pick it back up cleanly.

Work is organized by **topic**, which is a thread that can span many sessions. Because a handoff
is tied to its topic rather than the session, a workstream stays connected even after a `/clear`
rotates the session id underneath it.

## Install

```bash
# Add the marketplace
/plugin marketplace add gednyengs/claude-marketplace

# Install the plugin
/plugin install session-handoff@sekekama
```

Then restart or run `/reload-plugins`. Verify with `/plugin validate`.

## Quick start

Save where you are before you stop:

```
/session-handoff:save
```

Pick it back up later, even in a brand-new session after `/clear`:

```
/session-handoff:resume
```

`resume` works out the right topic on its own, checks whether the repository has moved since the
handoff was written, recaps the task, and asks how you want to proceed.

You don't have to type the commands. You can also trigger the same workflow by telling the agent
what you want in plain language, for example "save a handoff" or "where did we leave off?". The
bundled skill picks it up and runs the matching command.

## Commands

### `/session-handoff:save [note] [--topic <slug>]`

Capture the current session to a new handoff. It takes a project snapshot first (git state plus
detected build, test, and run commands), then writes a structured handoff. If you don't pass
`--topic`, it reuses the topic your session is already on, or starts a new timestamped one if the
session doesn't have a topic yet (pass `--topic` to name a new topic). An optional note is handed to
the agent as extra information to reflect in the handoff, for example a detail or fact to preserve, a
constraint, or something to emphasize. It informs the content; it does not name the topic.

When the topic already has a handoff, the new one replaces it as the topic's latest, so the agent is
pointed at the previous file and told to carry forward whatever is still in force (constraints,
decisions, dead ends, lessons, pending decisions) and drop what has been resolved.

### `/session-handoff:resume [--auto] [<id|topic>]`

Load the right topic and get ready to continue. With no argument it finds the most relevant topic
for your session, including one you just cleared out of. Pass an id or a topic slug to target a
specific one. It recaps the task and asks how to proceed. Add `--auto` to start executing the saved
next steps right away.

A handoff describes the past, so `resume` checks it against the present before the agent relies on
it. Ahead of the handoff it prints how long ago the file was saved and a **state check**:

- `CLEAN`: same branch, and every tracked or untracked file has the content it had when the handoff
  was saved. Committing your work or the handoff afterwards doesn't change this, because the check
  compares file contents, not commit ids.
- `DRIFT`: something moved. It lists the files that differ, a branch switch, and any file the
  handoff names that no longer exists.
- `UNVERIFIED`: the handoff could not be fully checked (it predates 3.4.0, or the project isn't a
  git repository), so the agent checks by hand.

The check covers the whole repository, including symlinks, submodules, and nested repositories. It
does not look at files git ignores or at what is staged, and it leaves out handoff folders and
Claude Code's agent worktrees. To stay fast it stops reading file contents after 32 MB of changes
and compares the rest by size and modification time.

Without git there is no commit to compare, so the check looks at the files the handoff names: a
named file that was modified after the handoff was saved is `DRIFT`. Files the handoff doesn't
name aren't checked, so the best result outside git is `UNVERIFIED`.

`--auto` executes straight away only on `CLEAN`, and only for a handoff this machine saved. The
plugin keeps a local record of the handoffs it writes; one that arrives from a teammate or another
clone, or that was edited after it was saved, is somebody else's plan, so the agent recaps its next
steps and asks first. The same applies to handoffs saved before 3.4.0, and to your own handoffs
after you move or rename the project directory, since no record matches them. On `UNVERIFIED` the agent does the by-hand check and executes only if
everything matches. On `DRIFT` it stops, reports what changed, and asks. Either way,
the agent re-asks any decision the handoff says was waiting on you instead of assuming an answer,
skips steps that depend on one, and checks on any agent or message the handoff lists as in flight
before relying on it. (A background subagent keeps running across `/clear` and reports to the next
session; it stops when Claude Code exits.)

If the newest file in the topic is an automatic compaction snapshot and the topic also has a
handoff you saved by hand, `resume` names that file too, so its dead ends and constraints aren't
hidden behind the snapshot.

### `/session-handoff:load <id|topic>`

Pull any topic's handoff into context for reference without switching your current topic. Handy
when you want to consult related work. The reference is remembered, so your next save records it
as a dependency link.

### `/session-handoff:list [MAX] [--any]`

Browse handoffs in your current topic, newest first. Add `--any` to see the latest handoff for
every topic in the project. It's read-only, and each row's id works with `load` and `resume`.

### A note on command arguments

Claude Code substitutes a slash command's arguments into the command body as plain text, so the
arguments you type reach the underlying script through your shell. Shell metacharacters are
therefore live: `;`, `|`, `&&`, backticks, `$(…)`, and unbalanced quotes will be interpreted rather
than passed through. In practice this bites on ordinary prose — `/session-handoff:save fix the
parser's bug` ends in an unterminated quote and the command fails.

Keep notes free of shell punctuation, or quote the whole note:

```
/session-handoff:save "fix the parser's bug"
```

Nothing here crosses a privilege boundary — it is your own shell, running commands you typed — but
it does mean a note is not a free-text field.

## What it captures

Each handoff records:

- **Task & progress**: the goal, how to tell it's finished, and what's done, in progress, and not
  started.
- **Constraints & instructions from the user**: the standing rules you gave ("don't touch the
  migrations", "use pnpm"), quoted where the wording matters, so a fresh session keeps to them.
- **Decisions waiting on the user** (when relevant): questions you haven't answered yet, with the
  options offered, the agent's recommendation, and which steps each one blocks.
- **Key decisions & rationale**: so settled questions don't get reopened.
- **Files & code touched**: the files and functions central to the work, and why each matters.
- **Approaches tried & dead ends** (when relevant): attempts that failed or were abandoned, so the
  next session doesn't waste time repeating them.
- **Lessons learned** (when relevant): how to work on this from here on, learned from a mistake or
  a correction. Lessons that would hold beyond the topic are flagged as candidates for `CLAUDE.md`.
- **Agents & messages in flight** (when relevant): subagents still running with the brief each was
  given and where its output lands, replies still awaited, and messages drafted but not yet sent.
- **Open questions & blockers**: what's unresolved or waiting on something external.
- **Next steps**: how to confirm the state before changing anything, then an ordered checklist. If
  work stopped mid-step, the first item quotes exactly where.
- **Environment, commands & results**: how to build, test, and run (auto-detected from
  `package.json`, `Makefile`, `pyproject.toml`, `Cargo.toml`, `go.mod`, Gradle, Maven, and more),
  plus the commands you actually ran and their results, each with the commit it ran against, and
  paths to any data files or artifacts the next session needs.
- **Repo snapshot**: branch, working-tree status, and recent commits.

The agent is also asked to say how it knows: a diagnosis or an in-progress item is marked as
verified (with the command that showed it) or as an assumption. The handoff's frontmatter records
the commit, branch, and a fingerprint of the file contents that differ from that commit, which is
what `resume` compares against later.

Recorded constraints are still file content, and a handoff can come from a teammate or another
branch. On resume the agent follows recorded rules that restrict what it does, and asks you before
acting on any that would grant it a permission or skip a safeguard.

Handoffs you save by hand are plain Markdown meant to be committed with your repo, so they travel
well for async work and team handoffs.

## Automatic safety net

The plugin protects your context without being asked:

- **Before compaction**, it writes a safety snapshot with real git and environment facts, and steers
  Claude Code's compaction summary toward what a handoff needs — the in-flight step, your
  constraints, decisions and their rationale, questions still waiting on you, blockers, lessons,
  agents and messages in flight, and the files touched. It also tells the summarizer not to
  reproduce secrets.
- **After compaction**, it persists Claude Code's own summary into that snapshot as the durable
  handoff body, so even an unattended auto-compaction leaves behind a complete handoff that survives
  `/clear`. On automatic compaction it also nudges the session to continue its in-flight work.
- **After `/clear`**, the next session recognizes the topic you just cleared and offers to resume
  it.
- **On session start**, you get a short list of recent topics so you can pick one back up.

## What you can rely on

- **Safe with several sessions at once.** Each session writes only its own timestamped,
  session-tagged files, so concurrent sessions in the same project never fight over files or create
  merge conflicts.
- **No lost topic on a crash or restart.** The plugin's internal bookkeeping self-heals: a session
  that crashes before it can clean up is reclaimed automatically after a while, and resuming the
  same session never forgets its topic. A session you move to the background on exit keeps its
  topic too, even though Claude Code gives it a new session id.
- **Your files stay yours.** The plugin never edits your `.gitignore` or forces anything into git.
  It writes the files and lets your project decide what's tracked.
- **Low overhead.** It only touches your context at the moments that matter (compaction, session
  start and end, and the commands you run), so it adds almost nothing to a normal turn.
- **Works without git.** `git` only enriches the repo snapshot. Without it you still get everything
  else.

One thing to know: the git snapshot reflects the whole working tree, so saving a handoff while
another session has uncommitted edits in the same checkout can attribute those edits to the wrong
handoff. Use separate git worktrees if that matters for your workflow.

## Keeping handoffs in git

Saved handoffs live under `.claude/sekekama/session-handoff/handoffs/<topic>/`. Whether they are
tracked is entirely your project's call — the plugin never edits `.gitignore` and never forces
anything into git. If your project doesn't ignore `.claude/`, they're committed like any other file
and travel to your teammates.

If your project **does** ignore `.claude/` wholesale, handoffs still work perfectly, but they stay
local: nothing is shared. The first time you save into an ignored location the plugin says so once,
so the setup is never silent. To track them, ignore `.claude/` granularly (for example, only
`.claude/settings.local.json`) rather than the whole directory — git can't re-include a subtree
under a fully ignored `.claude/`. The plugin's temporary bookkeeping normally lives outside
the repo; if Claude Code supplies no plugin-data directory it falls back to an in-repo `.state/`
that ships with its own `.gitignore`, so it is never committed either way.

**Review auto-snapshots before you commit them.** A handoff you write by hand is composed under an
explicit instruction to keep secrets out. The `-auto.md` snapshots are different: their body is
Claude Code's compaction summary of the whole conversation, persisted verbatim. The plugin asks the
summarizer to leave secrets out, but that is a request to a model, not a filter. If a token, key, or
`.env` value was pasted into that conversation, it can still land in the file — and committing it
puts it in your history. If your work involves credentials, either read auto-snapshots before staging them
or ignore `*-auto.md` and rely on `/session-handoff:save` instead.

## Migrating from v1

The first time v2 runs, it copies any legacy `.handoff/*.md` files into a `legacy` topic and leaves
your originals untouched (it's copy-before-delete and safe to run more than once). A short tombstone
in `.handoff/README.md` points to the new location. Once you've confirmed the move, you can delete
`.handoff/`. Browse the result with `/session-handoff:list --any` or
`/session-handoff:resume legacy`, or run the migration by hand anytime with `scripts/migrate.py`.

## Optional: compaction guidance in CLAUDE.md

Claude Code honors a `# Compact instructions` section in your project `CLAUDE.md`. Adding this
helps compaction preserve the right things:

```markdown
# Compact instructions

When compacting, preserve:
- the most recent handoff under .claude/sekekama/session-handoff/handoffs/
- current task state, blockers, and next steps
- key decisions and constraints
```

## Development

The test suite is standard-library `unittest` with no fixtures on disk — each test builds a
throwaway project directory:

```bash
python3 plugins/session-handoff/tests/test_session_handoff.py
# or
python3 -m unittest discover -s plugins/session-handoff/tests
```

It covers the compaction-summary parser (which is coupled to a Claude Code output format that can
drift), path containment and the topic-slug grammar, the `/clear` baton protocol, the GC sweep,
legacy migration, the recorded repo state and the resume-time state check, and an end-to-end run of
the command scripts as the slash commands invoke them.

What a handoff contains is defined in one place, `skills/session-handoff/templates/HANDOFF_TEMPLATE.md`,
and what to do with a loaded handoff in another, `skills/session-handoff/references/resume-protocol.md`.
The slash commands inject those files and the skill reads them, so edit them there.

## Requirements

- Claude Code CLI
- `python3` (the scripts are pure standard library, with no third-party packages)
- `git` (optional; it enriches the repo snapshot, and the plugin works fine without it)

## License

MIT

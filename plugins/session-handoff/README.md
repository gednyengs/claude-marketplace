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

`resume` works out the right topic on its own, recaps the task, and asks how you want to proceed.

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

### `/session-handoff:resume [--auto] [<id|topic>]`

Load the right topic and get ready to continue. With no argument it finds the most relevant topic
for your session, including one you just cleared out of. Pass an id or a topic slug to target a
specific one. It checks that the saved repo snapshot still matches your working tree, recaps the
task, and asks how to proceed. Add `--auto` to skip the recap and start executing the saved next
steps right away.

### `/session-handoff:load <id|topic>`

Pull any topic's handoff into context for reference without switching your current topic. Handy
when you want to consult related work. The reference is remembered, so your next save records it
as a dependency link.

### `/session-handoff:list [MAX] [--any]`

Browse handoffs in your current topic, newest first. Add `--any` to see the latest handoff for
every topic in the project. It's read-only, and each row's id works with `load` and `resume`.

## What it captures

Each handoff records:

- **Task & progress**: the goal, and what's done, in progress, and not started.
- **Key decisions & rationale**: so settled questions don't get reopened.
- **Approaches tried & dead ends** (when relevant): attempts that failed or were abandoned, so the
  next session doesn't waste time repeating them.
- **Open questions & blockers**: what's unresolved or waiting on input.
- **Next steps**: an ordered checklist you can act on.
- **Environment, commands & results**: how to build, test, and run (auto-detected from
  `package.json`, `Makefile`, `pyproject.toml`, `Cargo.toml`, `go.mod`, Gradle, Maven, and more),
  plus the commands you actually ran, meaningful results or measurements, and paths to any data
  files or artifacts the next session needs.
- **Repo snapshot**: branch, working-tree status, and recent commits.
- **Resume instructions**: the first concrete actions to take when picking the work back up.

Handoffs you save by hand are plain Markdown meant to be committed with your repo, so they travel
well for async work and team handoffs.

## Automatic safety net

The plugin protects your context without being asked:

- **Before compaction**, it writes a snapshot of the session automatically. Even an unattended
  session that hits auto-compaction leaves behind a usable handoff with real git and environment
  facts.
- **After `/clear`**, the next session recognizes the topic you just cleared and offers to resume
  it.
- **On session start**, you get a short list of recent topics so you can pick one back up.
- **If an automatic snapshot was left unfinished**, it nudges Claude to complete it, then gets out
  of the way. There are no nagging loops.

## What you can rely on

- **Safe with several sessions at once.** Each session writes only its own timestamped,
  session-tagged files, so concurrent sessions in the same project never fight over files or create
  merge conflicts.
- **No lost topic on a crash or restart.** The plugin's internal bookkeeping self-heals: a session
  that crashes before it can clean up is reclaimed automatically after a while, and resuming the
  same session never forgets its topic.
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

Saved handoffs live under `.claude/sekekama/session-handoff/handoffs/<topic>/` and are committed
with your repo by default. If you ignore `.claude/`, ignore it granularly (for example, only
`.claude/settings.local.json`) rather than the whole directory, because git can't re-include a
subtree under a fully ignored `.claude/`. The plugin's temporary bookkeeping lives outside the
repo, so it's never committed either way.

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

## Requirements

- Claude Code CLI
- `python3` (the scripts are pure standard library, with no third-party packages)
- `git` (optional; it enriches the repo snapshot, and the plugin works fine without it)

## License

MIT

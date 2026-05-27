# Session Handoff

Preserve and restore working context across Claude Code sessions, agent switches, and
context-window compaction.

When you stop mid-task, switch focus, hit auto-compaction, or hand work to a teammate, the
expensive context is lost: what you were doing, the decisions you made and why, what's
blocking you, and how to run the thing. Session Handoff captures the **necessary and
sufficient** context into version-controlled `.handoff/` files so any later session can
pick up cleanly.

## What it captures

- **Task & progress** — the goal, what's done, in progress, and not started.
- **Key decisions & rationale** — so settled questions aren't reopened.
- **Open questions & blockers** — what's unresolved or waiting on input.
- **Next steps** — an ordered, actionable checklist.
- **Environment & commands** — how to build/test/run and reproduce the working state
  (auto-detected from `package.json`, `Makefile`, `pyproject.toml`, `Cargo.toml`,
  `go.mod`, Gradle, Maven, and more).
- **Repo snapshot** — branch, working-tree status, and recent commits.

Handoffs live in `.handoff/<YYYY-MM-DD-HHMMSS>.md` at the project root. They sort
chronologically, form a readable history, and are designed to be **committed with the
repo** — great for async and team handoffs. Auto-generated safety snapshots use the
`-auto.md` suffix.

## Commands

### `/session-handoff:save [note]`

Capture the current session to a new handoff file. Runs a deterministic project snapshot
first (git + detected commands), then writes a structured, concise handoff filled from the
conversation. Add an optional note to label the checkpoint.

### `/session-handoff:resume [--auto]`

Load the most recent handoff. By default it recaps the task, verifies the repo snapshot
still matches reality, and asks how to proceed. Pass `--auto` to start executing the
recorded next steps immediately.

You can also just ask in plain language ("save a handoff", "where did we leave off?") —
the bundled **session-handoff skill** triggers the same workflow.

## Automatic safety net

Three hooks protect context without you asking:

| Hook | Event | What it does |
| --- | --- | --- |
| `session-start.sh` | **SessionStart** | Injects the most recent handoff so a new or post-compaction session knows where things stood (output capped to keep token cost low). |
| `precompact.sh` | **PreCompact** | Writes a deterministic safety snapshot before compaction and asks Claude to enrich it while it still has full context. |
| `enforce.sh` | **Stop** | If the latest auto-snapshot still has `<!-- TODO -->` placeholders, nudges Claude (at most twice) to finish it, then gets out of the way. |

This means even an unattended session that hits auto-compaction leaves behind a usable
handoff with real git/environment facts.

## Install

```bash
# Add the marketplace
/plugin marketplace add gednyengs/claude-marketplace

# Install the plugin
/plugin install session-handoff@sekekama
```

Then restart or run `/reload-plugins`. Verify with `/plugin validate`.

## Design notes & differences

- **Low always-on cost.** Unlike approaches that inject a directive on *every* user prompt,
  this plugin only touches context at the two moments it's actually at risk — compaction
  and session start — plus deliberate `/save`. That keeps per-turn token overhead near zero.
- **Deterministic first, model second.** Git state and build commands are gathered by
  shell scripts (ground truth), and the model fills the judgment sections. The PreCompact
  snapshot is useful even if the model never enriches it.
- **Graceful degradation.** `jq` is used when present but never required; without it the
  plugin captures slightly less and skips Stop-hook enforcement rather than failing.
- **No loops, no nagging.** Enforcement is gated on unfilled auto-snapshots and capped at
  two attempts via a counter in the plugin's persistent data directory.
- **Team-friendly.** Timestamped per-handoff files avoid the merge conflicts a single
  rolling log invites.

## Optional: compaction guidance in CLAUDE.md

Claude Code honors a `# Compact instructions` section in your project `CLAUDE.md`. Adding
this helps compaction preserve the right things:

```markdown
# Compact instructions

When compacting, preserve:
- the most recent entry in .handoff/
- current task state, blockers, and next steps
- key decisions and constraints
```

## Requirements

- Claude Code CLI
- `bash` and `git`
- `jq` (optional — enables richer command detection and Stop-hook enforcement)

## License

MIT

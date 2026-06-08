# Session Handoff

Preserve and restore working context across Claude Code sessions, `/clear`, agent switches,
and context-window compaction — organized by **topic** so a workstream stays connected no
matter what rotates the session id.

When you stop mid-task, switch focus, hit auto-compaction, clear the context, or hand work to
a teammate, the expensive context is lost: what you were doing, the decisions you made and
why, what's blocking you, and how to run the thing. Session Handoff captures the **necessary
and sufficient** context into version-controlled handoff files so any later session can pick
up cleanly.

## Topics: the unit of continuity

A **topic** is a thread of work that spans many sessions. Claude Code's `session_id` is an
implementation artifact — `/clear` starts a brand-new one — so keying continuity on the
session breaks a workstream at every clear. v2 keys on the topic instead.

- A session **acquires a topic lazily** — the first time you save, resume, or load — and
  rarely needs to be named by hand (it's derived from your save note, or carried forward
  across `/clear`).
- Handoffs live under `.claude/sekekama/session-handoff/handoffs/<topic-slug>/`, named
  `YYYY-MM-DD-HHMMSS-<sessionid>[-auto].md` so they sort chronologically and never collide
  between concurrent sessions.
- Each file opens with YAML **frontmatter that is the source of truth** (`topic`,
  `topic_title`, `session_id`, `created`, `kind`, optional `note` and `depends_on`). The
  topic subdirectory is just organization — a misfiled file is still correctly attributed.

## What it captures

- **Task & progress** — the goal, what's done, in progress, and not started.
- **Key decisions & rationale** — so settled questions aren't reopened.
- **Open questions & blockers** — what's unresolved or waiting on input.
- **Next steps** — an ordered, actionable checklist.
- **Environment & commands** — how to build/test/run and reproduce the working state
  (auto-detected from `package.json`, `Makefile`, `pyproject.toml`, `Cargo.toml`, `go.mod`,
  Gradle, Maven, and more).
- **Repo snapshot** — branch, working-tree status, and recent commits.

Manual handoffs (`/save`) are portable and meant to be **committed with the repo** — great for
async and team handoffs. Auto-generated safety snapshots use the `-auto.md` suffix and belong
to the session that wrote them.

## Commands

### `/session-handoff:save [note] [--topic <slug>]`

Capture the current session to a new handoff. Runs a deterministic project snapshot first
(git + detected commands), resolves the topic (`--topic` → the session's recorded topic →
a new topic seeded from the note), writes a structured handoff with schema-2 frontmatter, then
records the topic and refreshes the per-directory pointer. Any pending cross-topic links
(from `/load`) are folded in as `depends_on`.

### `/session-handoff:resume [--auto] [<id|topic>]`

Load the right topic and prepare to continue. With no argument it resolves, in order: this
session's topic → a post-`/clear` baton → the only recent topic → otherwise a short **picker**
of recent topics to choose from. Pass an explicit `<id|topic>` to target one. It verifies the
repo snapshot still matches reality, recaps the task, and asks how to proceed — or, with
`--auto`, goes straight to executing the recorded next steps.

### `/session-handoff:load <id|topic>`

Pull **any** topic's handoff into context for reference (e.g. to consult related work) without
changing your current topic. If it belongs to a different topic, its id is recorded so your
next `/save` notes it as a `depends_on` cross-topic reference.

### `/session-handoff:list [MAX] [--any]`

Browse handoffs in the current topic (newest first), or with `--any` the latest handoff per
topic across the whole project. Read-only; each row's id feeds `/load` and `/resume`.

You can also just ask in plain language ("save a handoff", "where did we leave off?") — the
bundled **session-handoff skill** triggers the same workflow.

## Automatic safety net

Four hooks protect context without you asking:

| Hook | Event | What it does |
| --- | --- | --- |
| `session-start.py` | **SessionStart** | Source-aware: `resume` → no-op (transcript already restored); `compact` → a concise continue-nudge (auto) or light pointer (manual) to the snapshot; `clear` → recaps the topic you just cleared and offers `/resume` (or a picker if clears are ambiguous); `startup` → a short list of recent topics. Output capped; never silently adopts a topic. |
| `session-end.py` | **SessionEnd** | On `/clear`, leaves a per-directory "baton" carrying the cleared session's own topic so the next session can pick it back up. No eager deletion — state is reclaimed by age. |
| `precompact.py` | **PreCompact** | Writes a deterministic safety snapshot to the session's topic before compaction and asks Claude to enrich it (emphasizing the in-flight step) while it still has full context. |
| `enforce.py` | **Stop** | If the session's latest auto-snapshot still has `<!-- TODO -->` placeholders, nudges Claude (at most twice) to finish it, then gets out of the way. |

Even an unattended session that hits auto-compaction leaves behind a usable handoff with real
git/environment facts.

## Continuity across `/clear` & concurrency

`/clear` starts a **new** session id with no correlator to the old one except the working
directory. v2 bridges this with a small **baton**: `SessionEnd(clear)` appends the cleared
session's own topic to a per-directory clears log, and the next `SessionStart(clear)` claims
it (once), suggesting that topic — your `/resume` then continues it. Two concurrent clears in
the same directory are detected as ambiguous and degrade to a picker.

The plugin stays safe under **multiple concurrent sessions** in one project:

- Each session writes only its **own** timestamped, session-tagged handoff files — no write
  contention, no merge conflicts.
- Topic grouping derives from **frontmatter**, so any directory view is regenerable; a stale
  index is never load-bearing.
- **Ephemeral state lives outside the repo** in `$CLAUDE_PLUGIN_DATA` (fallback: a gitignored
  in-repo `.state/`), keyed per-session or per-directory, **line-oriented (`key=value` / TAB),
  never JSON**. It is reclaimed by an **age-based sweep** (default 14-day TTL), so a crash that
  skips `SessionEnd` self-heals and a `--resume` (same session id) never forgets its topic.

**Known limitation:** the git working-tree snapshot is shared across sessions, so a handoff
saved while another session has uncommitted edits in the same tree can misattribute those
changes. Use separate git worktrees if that matters for your workflow.

## Migrating from v1

The first time v2 runs (any command or a new session), it **copies** legacy `.handoff/*.md`
into the `legacy` topic at `.claude/sekekama/session-handoff/handoffs/legacy/`, synthesizing
schema-2 frontmatter from each filename. The migration is idempotent and copy-before-delete:
your originals are left untouched and a `.handoff/README.md` tombstone points to the new
location. Run it by hand any time with `scripts/migrate.py`. Delete `.handoff/` once you've
confirmed the move; browse the result with `/session-handoff:list --any` or
`/session-handoff:resume legacy`.

## Commit posture

The plugin is **commit-neutral**: it writes artifacts and lets your project's own `.gitignore`
decide what is tracked — it never edits `.gitignore` or forces tracking. To **keep handoffs in
git**, ignore `.claude/` granularly (e.g. only `.claude/settings.local.json`), not wholesale —
git cannot re-include a subtree under a fully-ignored `.claude/`. Ephemeral state lives outside
the repo, so it is never committed either way.

## Install

```bash
# Add the marketplace
/plugin marketplace add gednyengs/claude-marketplace

# Install the plugin
/plugin install session-handoff@sekekama
```

Then restart or run `/reload-plugins`. Verify with `/plugin validate`.

## Design notes & differences

- **Low always-on cost.** The plugin only touches context at the moments it's actually at risk
  — compaction, session start/end — plus deliberate `/save`, `/resume`, `/load`, `/list`. That
  keeps per-turn token overhead near zero.
- **Deterministic first, model second.** Git state and build commands are gathered by the
  scripts (ground truth); the model fills the judgment sections. The PreCompact snapshot is
  useful even if the model never enriches it.
- **Pure standard library.** The scripts are `python3` stdlib only — `json` parses hook payloads
  and `package.json` directly, so there is no `jq` dependency and ephemeral state stays
  line-oriented. The only external tool is `git` (for the repo snapshot), and it degrades gracefully.
- **No loops, no nagging.** Stop-hook enforcement is gated on unfilled auto-snapshots and
  capped at two attempts via a per-session counter.
- **Team-friendly.** Timestamped, session-tagged per-handoff files avoid the merge conflicts a
  single rolling log invites; shared per-directory state is updated via locked atomic writes.

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
- `python3` (the plugin's scripts are pure standard library — no third-party packages)
- `git` (optional — enriches the repo snapshot; the plugin degrades gracefully without it)

## License

MIT

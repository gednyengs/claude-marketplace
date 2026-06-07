# Changelog

All notable changes to this plugin are documented here. This project follows
[semantic versioning](https://semver.org).

## [2.0.0] — 2026-06-07

Topic-based redesign. The unit of continuity is now a **topic** — a thread of work that
spans many sessions — instead of the Claude Code `session_id`. Because `/clear` starts a
brand-new session id, v1's session keying severed a workstream at every clear; topics
survive `/clear`, restarts, and compaction. Existing v1 handoffs are migrated automatically
(copy, not move) the first time v2 runs. Grounded in empirically verified session-lifecycle
behavior; design hardened by an external review (see `docs/V2-SPEC.md`).

### Breaking
- **New on-disk layout.** Handoffs now live under
  `.claude/sekekama/session-handoff/handoffs/<topic-slug>/<timestamp>-<sessionid>[-auto].md`
  instead of `.handoff/`. The org-namespaced path keeps the plugin's artifacts together.
- **Frontmatter is the source of truth.** Every handoff opens with YAML frontmatter
  (`schema: 2`, `topic`, `topic_title`, `session_id`, `created`, `kind`, optional `note`
  and `depends_on`). The topic subdirectory is human-facing organization only — a misfiled
  file is still correctly attributed by its frontmatter.
- **Handoff ids are `<topic>/<timestamp>-<sessionid>`** (a bare topic slug means "latest
  manual handoff in that topic"). Accepted by `/resume` and `/load`.

### Added
- **`/session-handoff:load <id|topic>`** — pull any topic's handoff into context for
  reference without changing the session's current topic; records a cross-topic
  `depends_on` link for the next save.
- **`/session-handoff:list [MAX] [--any]`** — browse handoffs in the current topic, or the
  latest per topic across the whole project.
- **`/session-handoff:save … [--topic <slug>]`** — pin the save to a specific topic; also
  resolves the topic from the session's recorded topic, else starts a new one (seeded from
  the note).
- **`/session-handoff:resume [<id|topic>]`** — resume a specific topic/handoff; bare
  `/resume` resolves by session topic → post-`/clear` baton → single recent topic → picker.
- **SessionEnd hook** — on `/clear`, leaves a per-directory "baton" carrying the cleared
  session's own topic so the next session can pick it back up.
- **Automatic v1→v2 migration** (`scripts/migrate.sh` + `hb_migrate_legacy`) — copies legacy
  `.handoff/*.md` into `handoffs/legacy/` with synthesized schema-2 frontmatter. Idempotent,
  copy-before-delete, partial-failure safe; runs opportunistically and leaves a tombstone.
- New scripts: `save-record.sh` (commits a save's side effects after the file is written),
  `load.sh`, `list.sh`, `migrate.sh`.
- Cross-session/cross-clear continuity primitives: a durable per-directory topic pointer,
  an append-only clears log with claim-once semantics, and concurrent-`/clear` ambiguity
  detection (degrades to a picker).

### Changed
- **SessionStart is now source-aware** (verified behavior): `resume` → no-op (the transcript
  is already restored); `compact` → a concise continue-nudge (auto) or light pointer (manual)
  to the snapshot; `clear` → recaps the cleared topic (claimed from the clears log) or shows
  a picker; `startup` → a short list of recent topics. It never silently adopts a topic.
- **Ephemeral state moved out of the repo** into `$CLAUDE_PLUGIN_DATA` (fallback: a gitignored
  in-repo `.state/`), keyed per-session or per-directory, and is **line-oriented (`key=value`
  / TAB) — never JSON**, so the plugin no longer depends on `jq` for any state.
- **Reclamation is age-based** (`hb_gc_sweep`, default 14-day TTL, throttled): a crash/kill
  that skips `SessionEnd` self-heals, and a `--resume` (same session id) never forgets its
  topic — replacing v1's eager-on-exit cleanup.
- **Commit posture is neutral**: the plugin writes artifacts and lets the project's own
  `.gitignore` decide what is tracked; it never edits `.gitignore`.
- `scripts/lib.sh` rewritten around the topic model (paths, frontmatter, ids, slugs, pointer,
  clears log, migration). `new-path.sh` now resolves the topic and prints a ready-to-paste
  frontmatter block; `resume.sh` records topic adoption on a single resolve.

### Migration notes
- First v2 run copies `.handoff/*.md` into the `legacy` topic and writes a `.handoff/README.md`
  tombstone. Originals are left untouched — delete `.handoff/` once you've confirmed the move.
- **To keep handoffs tracked in git**, a project must ignore `.claude/` granularly (e.g. only
  `.claude/settings.local.json`), not wholesale — git cannot re-include a subtree under a
  fully-ignored `.claude/`. Ephemeral state lives outside the repo, so it is never committed.

## [1.2.0] — 2026-05-28

### Fixed
- `save` → `/clear` → `resume` no longer reports the just-saved handoff as "from another
  session." `/clear` starts a new session id, so the handoff (tagged with the pre-clear
  session) was treated as foreign. `/resume` is now permissive for this explicit flow.

### Changed
- `/session-handoff:resume` resolves the no-own-handoff case by candidate count: zero →
  the usual "no handoff" message; exactly one → load it directly (the common post-`/clear`
  case), presented as a valid portable handoff; two or more → a numbered picker of up to 5
  recent manual handoffs (newest first, deduped to the latest per session, each with a
  one-line task summary) to choose from. `--auto` loads the newest manual handoff.
- SessionStart wording softened; on `source: "clear"` it points to `/resume` to pick up
  the most recent checkpoint. SessionStart stays conservative (passive injection of this
  session's own handoff only); the permissiveness is limited to the explicit `/resume`.

### Added
- `hb_recent_manual`, `hb_handoff_summary`, and `hb_handoff_when` helpers in `lib.sh`
  (portable; no bash-4 associative arrays).

## [1.1.0] — 2026-05-28

### Added
- Session-scoped handoffs: filenames now carry a short session id
  (`<timestamp>-<sessionid>.md`, and `-auto.md` for safety snapshots) so concurrent
  Claude Code sessions in the same project no longer collide or overwrite each other.
- `scripts/new-path.sh` — reserves the exact session-tagged path `/save` writes to.
- Atomic handoff writes (temp file + `mv`) and an `flock`-guarded, per-session Stop-hook
  counter (`enforce.<sessionid>.count`), both degrading gracefully where unavailable.

### Changed
- Session id is resolved from the hook stdin `session_id` (guaranteed), falling back to the
  transcript-path basename, then the `CLAUDE_CODE_SESSION_ID` env var, then a degraded
  `nosession` bucket.
- SessionStart now injects **this session's** own latest handoff; if the session has none,
  it surfaces the newest *manual* handoff clearly labeled as belonging to another session
  (never silently adopts foreign context).
- `/session-handoff:resume` prefers this session's handoff and otherwise lists portable
  manual handoffs to choose from; `--auto` only auto-continues this session's own handoff.

### Fixed
- The Stop hook no longer blocks an unrelated session's stop to demand it fill in another
  session's pre-compaction snapshot. It only ever acts on the current session's own
  auto-snapshot, and never enforces a session it cannot identify.

### Known limitations
- The git working-tree snapshot is shared across sessions, so a handoff can still
  misattribute another concurrent session's uncommitted changes (a git-worktree concern,
  out of scope for session-id keying).

## [1.0.0] — 2026-05-27

### Added
- `/session-handoff:save` command — writes a structured handoff to
  `.handoff/<timestamp>.md` from a deterministic project snapshot plus the conversation.
- `/session-handoff:resume` command — loads the newest handoff, verifies repo drift, and
  recaps or auto-continues (`--auto`).
- `session-handoff` skill — natural-language trigger for the same save/resume workflow.
- SessionStart hook — injects the most recent handoff into new and post-compaction sessions
  (output capped to bound token cost).
- PreCompact hook — writes a deterministic safety snapshot before compaction and asks the
  model to enrich it.
- Stop hook — nudges (up to twice) to fill unfilled auto-snapshot placeholders, then yields.
- Build/test/run command detection for Node, Make, Python, Rust, Go, Ruby, Maven, Gradle,
  and Docker Compose.
- Graceful degradation when `jq` is unavailable.

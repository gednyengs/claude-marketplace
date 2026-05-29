# Changelog

All notable changes to this plugin are documented here. This project follows
[semantic versioning](https://semver.org).

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

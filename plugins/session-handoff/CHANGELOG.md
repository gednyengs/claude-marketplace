# Changelog

All notable changes to this plugin are documented here. This project follows
[semantic versioning](https://semver.org).

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

# Changelog

All notable changes to this plugin are documented here. This project follows
[semantic versioning](https://semver.org).

## [3.3.0] — 2026-07-24

A correctness and containment release, prompted by a full audit of the plugin (self-review plus an
independent external review). No change to the `/save`, `/resume`, `/load`, `/list` interface and no
on-disk format change; existing handoffs and topics keep working untouched.

### Fixed — containment
- **A handoff's `topic` frontmatter can no longer redirect where the plugin writes.** The field was
  treated as authoritative session state, and `os.path.join` lets an absolute value swallow the base
  path — so a committed handoff carrying `topic: /tmp/x` would make a later PreCompact write its
  snapshot *outside the repository*. Topics are now validated as a single plain path component
  (`lib.valid_slug`/`safe_slug`) at every point one enters — frontmatter, `--topic`, the `/clear`
  baton, the session binding — and `topic_dir()` refuses a malformed slug outright. The grammars are
  applied with `fullmatch()`: Python's `$` also matches just before a terminal newline, so an
  anchored `^…$` would have accepted `"safe\n"` — a value that then reaches a path, or lands in
  frontmatter as two lines.
- **Discovery no longer follows symlinks out of the handoff tree.** `latest_ready_in_topic()`,
  `recent_topics()` and `all_handoffs_bytime()` performed no containment check, so a symlink
  committed into a topic directory could make `resume` read and echo an arbitrary file into model
  context. All three now apply the same `realpath` containment test `resolve_id()` already used, and
  `resume`/`load` re-check at the moment of opening (resolution and open are separate operations).
- **`resolve_id()` no longer passes glob metacharacters to `glob.glob` unescaped**; both halves of an
  id are matched against an explicit grammar first, and escaped as a backstop.
- **Handoff content is fenced as data.** `resume` and `load` wrap the body in BEGIN/END markers and
  state that it is file content rather than instructions. The markers are **derived per file**
  (`lib.fence`) and guaranteed absent from the body — a fixed marker would be forgeable by a handoff
  that simply contains the end marker, making everything after it look like it fell outside the
  boundary. Titles and summaries injected by the hooks are flattened to one bounded line
  (`lib.sanitize_line`), and `fm_quote()` flattens newlines so a title carried forward from an
  earlier handoff cannot inject frontmatter keys into a new one.

### Fixed — lifecycle
- **Two sessions can no longer merge into one topic.** `unique_topic_slug()` used a check-then-create
  test, so two topicless sessions starting in the same second both settled on `topic-<ts>`. The slug
  is now reserved atomically with `os.mkdir`, and the function never returns a name it has not
  attempted to claim (the old bounded loop fell out and returned `<base>-999` unreserved).
- **The GC sweep no longer deletes the live session's own state.** Session files were reclaimed on
  age alone, so a session resumed from a transcript older than the TTL could have its topic binding
  deleted by its own sweep. Callers now pass `keep_sid`.
- **Degraded sessions no longer share topic state or snapshots.** When no session id is available,
  PreCompact and PostCompact previously read and wrote the shared `nosession` binding, letting one
  unidentified session adopt another's topic. They now neither read nor write it, and take a fresh
  topic instead. Skeleton adoption is also disabled there: since every degraded run resolves to the
  same key, matching a summary to a snapshot by recency could complete a *different* session's file.
  A degraded PreCompact publishes its snapshot `complete` immediately, and a degraded PostCompact
  always writes its own separate handoff.
- **PostCompact always finishes what PreCompact announced.** If no usable compaction summary
  arrived, it returned early and left a `status: pending` file that `list`/`resume` hide — after
  SessionStart had already told the user a handoff was saved. It now completes the snapshot with an
  explicit "summary unavailable" body over the repo facts, and says so on stdout.
- **A failed state write is reported instead of swallowed.** `save-record.py` printed "Recorded"
  even when the session→topic binding could not be written (unwritable state directory); it now
  fails with an actionable message. `save-record.py` also verifies the handoff path is inside the
  handoff directory before recording.
- **Legacy migration backfills schema-2 frontmatter.** A v1 handoff that already began with `---` was
  copied verbatim, landing with no `topic:` — migrated but invisible to discovery. Missing keys are
  now spliced in without disturbing existing ones.

### Fixed — documentation
- `commands/save.md` was missing the **`Files & code touched`** section that `SKILL.md` and the
  template require and that the 3.2.0 notes claimed was added, so `/session-handoff:save` and the
  natural-language skill produced structurally different handoffs. It also now carries the verbatim
  in-flight quote requirement in `Next steps`.
- The 3.2.0 claim that pending snapshots are "reclaimed by the age sweep" **was never true** — the
  sweep only ever touches ephemeral state, by design (`V2-SPEC.md`). The docs now say what actually
  happens: an abandoned pending snapshot is inert and hidden, and is removed by hand. No code was
  added to delete committed handoffs.
- README documents that slash-command arguments reach the shell as typed, so a note containing shell
  metacharacters (notably an apostrophe) breaks the command — quote the note.
- README warns that `-auto.md` snapshots embed Claude Code's summary of the whole conversation
  verbatim, with none of the "no secrets" discipline the manual path applies, and should be reviewed
  before being committed.

### Added
- **A one-time notice when handoffs land somewhere git ignores.** `V2-SPEC.md` §3.3 specified this
  ("on first write it emits a one-time notice") but it was never implemented, so a project with a
  wholesale `.claude/` ignore silently got local-only handoffs while the docs described a shareable
  artifact. The commit posture is unchanged and still neutral — the plugin never edits `.gitignore`.
- **A test suite** (`tests/test_session_handoff.py`, 90 tests, standard library only): compaction
  summary parsing, the slug grammar and path containment, symlink escape, the `/clear` baton, the GC
  sweep, frontmatter parsing, legacy migration, the PreCompact/PostCompact hooks driven as processes
  with real payloads, and an end-to-end run of the command scripts. Every defect above has a named
  regression test.
- Hook and command scripts are now importable (`if __name__ == "__main__":`) so they can be tested.

### Changed
- Frontmatter is parsed in **one pass** (`lib.fm_all`), halving the file reads `recent_topics()` did
  per handoff on the session-start path. Arbitrary key text is preserved, matching what the old
  per-key scanner accepted — restricting keys to identifiers would have silently dropped hyphenated
  or digit-leading keys in handoffs already on disk.

### Removed
- **The per-directory `<cwd-hash>.ptr` pointer.** Nothing ever read it back, so every save and resume
  paid a lock and three rewrites to maintain state no resolution path consulted. Leftover `.ptr`
  files are reclaimed by the sweep. `ptr_topic()`, `latest_for_session()` and
  `latest_manual_in_topic()` are gone with it.

## [3.2.0] — 2026-06-08

Compaction handoffs now piggyback on Claude Code's own compaction summary instead of leaving an
unfilled skeleton for the model to complete. A new **PostCompact** hook persists that summary as the
durable handoff body, and the **Stop** hook (which nagged the model to fill `<!-- TODO -->`
placeholders) is removed. No change to the `/save`, `/resume`, `/load`, `/list` interface; the
on-disk layout is unchanged and old handoffs remain readable.

### Added
- **PostCompact hook.** Receives Claude Code's generated compaction summary and writes it into the
  pre-compaction snapshot as the handoff body, flipping the snapshot's `status` from `pending` to
  `complete`. That summary is what Claude Code injects in-context after compaction; persisting it
  makes the content survive `/clear`, restarts, and new sessions. If compaction skipped PreCompact
  (reactive prompt-too-long compaction), PostCompact creates a completed handoff from scratch. Only
  the `<summary>` portion is kept — Claude Code's summary arrives wrapped as
  `<analysis>…</analysis><summary>…</summary>` and does *not* strip the analysis itself, so PostCompact
  drops that chain-of-thought and persists just the clean 9-section handoff.
- **`Files & code touched` section** in the manual handoff template, plus a verbatim in-flight quote
  requirement in `Next steps`, to reduce drift when resuming mid-edit.
- **Auto-snapshot frontmatter** now carries `status` (`pending`/`complete`) and `compact_trigger`
  (`auto`/`manual`). Pending snapshots (compaction aborted before PostCompact) are hidden from
  `list`/`resume` and reclaimed by the age sweep.
  > **Correction (3.3.0):** the reclamation half of that sentence was never true — the sweep only
  > ever touches ephemeral state, never a committed handoff. An abandoned pending snapshot is inert
  > and stays on disk until deleted by hand. 3.3.0 also makes abandonment far rarer by always
  > completing a snapshot PostCompact was told about.

### Changed
- **PreCompact** no longer writes `<!-- TODO -->` placeholders or asks the model to fill the file by
  hand (the compaction summarizer has no tools and cannot). It writes a `pending` safety snapshot
  with git + environment facts and steers Claude Code's compaction summary toward handoff essentials
  — appended *after* any `/compact` text you typed, additive and never replacing it.
- **Auto-snapshots are now first-class for resume.** `resume`, `list --any`, and the recent-topics
  surfaces consider completed auto-snapshots of any kind, so a session that only ever auto-compacted
  is resumable. Manual `/compact` also produces a durable handoff.
- **SessionStart(compact)** distinguishes auto (continue-nudge) from manual (quiet pointer), with a
  soft conditional fallback for reactive compaction (which records no trigger).

### Removed
- **Stop hook (`enforce.py`).** It nagged the model (up to twice) to fill auto-snapshot
  placeholders, which forced extra model turns. PostCompact now fills the body automatically for
  free, so the gate is obsolete; removing it eliminates those turns.

## [3.1.0] — 2026-06-08

Additive capture improvements: an optional dead-ends section and a richer environment section. No
breaking changes; the on-disk layout and frontmatter schema are unchanged.

### Added
- **Optional `## Approaches tried & dead ends` section.** When a session hit attempts that would be
  expensive or tempting to repeat, the handoff now records what was tried and why it failed, so the
  next session doesn't rediscover the dead end. It is included only when there are such attempts and
  omitted otherwise.

### Changed
- **`## Environment & commands` is now `## Environment, commands & results`.** Beyond build/test/run
  commands, it also captures the commands actually run this session, meaningful pass/fail results or
  measurements, and paths to data files or artifacts the next session needs. The deterministic
  snapshot (`snapshot.py`) emits the new heading, so manual saves and auto-snapshots stay consistent.
- **README:** the "What it captures" list now includes `Resume instructions` (previously omitted)
  alongside the two items above.

## [3.0.0] — 2026-06-08

Breaking change to the optional `/save` note. The note is now **extra context the agent folds into
the handoff** instead of a way to name the topic. Because `/save "some text"` now does something
different, this is a major bump; the on-disk layout and frontmatter schema are unchanged.

### Breaking
- **`/save [note]` no longer names the topic.** A note passed to `/save` is relayed to the model as
  an `ADDITIONAL CONTEXT` block: extra information the user wants reflected in the handoff (a detail
  or fact to preserve, a constraint to record, or something to emphasize). It is no longer used to
  derive the topic slug or title, and it is no longer written into the handoff frontmatter. A new
  unnamed topic now always gets a `topic-<timestamp>` slug, and the model refines that into a human
  `topic_title` from the conversation (as it already did). Pass `--topic <slug>` to name a topic.
  The relayed note is delimited and flagged as user content, so it is not interpreted as workflow
  instructions.

### Migration
- If you relied on `/save "some text"` to name a new topic, pass `--topic some-slug` instead.
  Existing handoffs and topics are unaffected; the on-disk layout and frontmatter schema are the
  same (the optional `note` field simply stops being auto-populated).

## [2.1.0] — 2026-06-08

Bug-fix + maintenance release. **No change to behavior, commands, on-disk layout, or frontmatter** —
existing handoffs and ephemeral state keep working unchanged. The support scripts are rewritten from
bash to Python (standard library only), which also fixes a path-resolution bug.

### Fixed
- **Handoffs no longer land in the wrong directory.** The scripts computed the project root from
  `${CLAUDE_PROJECT_DIR:-$(pwd)}`, but Claude Code does not export `CLAUDE_PROJECT_DIR` into the
  command/`!`-injection subprocess (it text-substitutes the token into the command line, and only
  *hooks* get the env var). So `/save` (and `resume`/`load`/`list`) fell back to `pwd` — often a
  drifted **subdirectory** — and wrote handoffs and `.state/` pointers under
  `<repo>/<subdir>/.claude/sekekama/session-handoff/` instead of the repo root. The project dir is
  now captured from an explicit `--project-dir "${CLAUDE_PROJECT_DIR}"` argument passed on every
  invocation line (hooks, `!`-lines, and model-run body commands), so resolution is correct
  regardless of the shell's working directory. A missing/invalid value errors loudly in command
  scripts and is a no-op in hooks — never a silent wrong-directory write.
- The ephemeral **state directory** is resolved the same way (uniform `--plugin-data`), so it can
  never split between an out-of-repo and an in-repo location across hook vs. command contexts.

### Changed
- **Scripts rewritten from bash to Python** (`scripts/*.sh` → `scripts/*.py`), invoked as
  `python3 .../X.py …`. Pure standard library — **`jq` is no longer used at all** (`json` parses hook
  payloads and `package.json` directly), and the `sha1`/date/locking helpers use `hashlib`/`datetime`/
  `fcntl`. On-disk formats (filenames, frontmatter, ephemeral state, cwd-hash) are byte-compatible.
- **Requirements:** `python3` (replaces `bash`); `git` remains optional (repo snapshot only); `jq`
  is no longer needed.

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

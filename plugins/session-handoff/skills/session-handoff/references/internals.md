# Session handoff internals

Background on how the plugin stores and tracks handoffs. None of this is needed to save or resume;
it is here for explaining or debugging the plugin. The full design is in `docs/V2-SPEC.md`.

## Topics and files

The unit of continuity is a **topic**: a thread of work that spans many sessions. Because `/clear`
starts a brand-new session id, handoffs are keyed on the topic (not the session) so a workstream
stays connected across `/clear`, restarts, and compaction. A session acquires a topic lazily, the
first time it saves, resumes, or loads.

Handoffs are markdown files under `.claude/sekekama/session-handoff/handoffs/<topic-slug>/`, named
`YYYY-MM-DD-HHMMSS-<sessionid>.md` so they sort chronologically and never collide between concurrent
sessions. Compaction snapshots use a `-auto.md` suffix. Manual handoffs are portable and meant to be
committed; auto-snapshots belong to the session that created them.

## Frontmatter

Each file opens with YAML frontmatter that is the source of truth; the topic subdirectory is just
human-facing organization. `new-path.py` prints the block for a manual handoff and the hooks write
it for an auto-snapshot.

```yaml
---
schema: 2
topic: <topic-slug>                       # stable kebab-case slug; the unit of continuity
topic_title: "<Human-readable title>"     # may be refined later without renaming the slug
session_id: <sid>                         # originating session (provenance + collision-avoidance)
created: <YYYY-MM-DDThh:mm:ss±zzzz>
kind: manual                              # manual | auto
head: <commit id>                         # repo state the handoff was written against
branch: <branch name>
tree_state: clean                         # clean | dirty-<fingerprint of the uncommitted changes>
note: "<optional one-line label>"         # not the /save note, which is folded into the body
depends_on:                               # optional; cross-topic handoff ids only
  - <other-topic>/<timestamp>-<sid>
status: complete                          # auto only: pending until PostCompact fills the body
compact_trigger: auto                     # auto only: auto | manual
---
```

`head`, `branch` and `tree_state` are absent outside a git repository, in a repository with no
commits, and in handoffs written before 3.4.0.

`tree_state` is `clean` when every file matches the recorded commit, and otherwise a digest of
every path whose working-tree content differs from that commit plus every untracked file. For each
path it takes the name and:

- for a file, its bytes and executable bit;
- for a symlink, its target;
- for a submodule (a path the index records as one), its checked-out commit and the digest of its
  own changes;
- for any other directory git reports whole, in practice an untracked nested repository, the files
  inside it, read directly. git is run inside a directory only when the index says it is a
  submodule, because running it anywhere else would execute that directory's own git config.

It covers the whole repository, not just the project directory. Not part of it: the plugin's own
`handoffs/` and `.state/` folders anywhere in the repository, untracked agent worktrees under
`.claude/worktrees`, files git ignores, files marked assume-unchanged, and the difference between
staged and unstaged. A file that starts or stops being tracked counts as changed even if its bytes
are the same.

Two things are compared that you might not expect. An untracked nested repository is read as plain
files, so its own ignore rules do not apply and its build output counts. And a linked worktree
kept inside the repository directory, anywhere other than `.claude/worktrees`, is an untracked
directory like any other, so edits made there count.

Two limits keep it cheap. Once 32 MB of changed content has been read, further files are compared
by size and modification time, so touching a very large changed file can read as a change. And a
nested repository with more than 20,000 files, or git taking more than 20 seconds in total, makes
the state unknown, which resume reports as `UNVERIFIED` rather than guessing.

## The state check on resume

`resume.py` recomputes that digest **against the commit the handoff recorded**, not against the
current HEAD, and compares. Because the comparison is about file content, the result does not
change when the saved work is committed afterwards, or when the handoff itself is: a file cannot
record the hash of the commit that contains it, so comparing commit ids would report every
committed handoff as changed. The verdict printed ahead of the handoff body is one of:

- `CLEAN` — same branch, and every file has the content it had at save time. If commits were made
  since, they are listed, with a note that they did not change what is on disk.
- `DRIFT` — something moved. The bullets say what: file content that differs from save time (with
  the paths, when the tree was clean at save), a branch switch, a recorded commit that is not in
  this repository, and any path under "Files & code touched" that no longer exists.
- `UNVERIFIED` — the handoff could not be fully checked: it records no commit or no `tree_state`,
  the state could not be determined within the limits above, or the project is not a git
  repository.

Without git there is no commit to compare, so the check looks only at the files the handoff names:
whether they exist, and whether they were modified after the handoff was saved (taking the earlier
of its `created` field and the file's own modification time). A named file modified since is
`DRIFT`. Otherwise the verdict stays `UNVERIFIED`, because files the handoff does not name were
not checked.

### Origin

The verdict is computed from frontmatter the file itself supplies, so it can say a handoff is not
stale but not who wrote it: a handoff that arrives through a clone can carry whatever values earn
`CLEAN`. The plugin therefore keeps a receipt for every handoff it writes on this machine, a hash
of the file as written, stored with its state outside the repository. Resume prints an `Origin:`
line saying whether the loaded file has a matching receipt. A handoff from a teammate or another
clone has none, and neither does one edited after it was saved. Line-ending conversion and
trailing newlines do not count as edits. Other things that lose the record: a handoff written by a
plugin version before 3.4.0, a project directory that was moved or renamed, and resuming from a
different checkout than the one that saved. Receipts are not written or trusted when the state
directory is the in-repo fallback (no plugin data directory), since a branch could carry a forged
one; in that setup `--auto` always asks first.

With `--auto` resume also prints `AUTO-RESUME:`. For a handoff with a receipt it is `OK`,
`CHECK FIRST`, or `HOLD` for the three verdicts. Without a receipt it is `REVIEW FIRST` (or `HOLD`
on drift): the next steps are someone else's plan, so the agent recaps them and asks.

Frontmatter is untrusted input. `head` is passed to git only when it is a full hexadecimal object
id, `tree_state` is compared and never printed, and `branch` is printed only when it is a plain ref
name. Names of changed files are printed only when they are plain path names; others are counted.
Discovery ignores any file whose name is not a well-formed `<timestamp>….md` handoff name, so a
file with a crafted name can neither be loaded nor reach the header.

Resume loads the newest ready file in a topic regardless of kind. When that file is an
auto-snapshot and the topic also has a hand-written handoff, the header names it on a
`Manual handoff:` line.

## Hooks

- **PreCompact** writes a deterministic safety snapshot (git + environment facts, `status: pending`)
  to the session's topic before the context window is compacted, and steers Claude Code's compaction
  summary toward handoff essentials: the in-flight step quoted verbatim, the user's constraints,
  decisions and rationale, unanswered questions to the user, blockers, lessons, agents and messages
  in flight, and files touched. It also tells the summarizer not to reproduce secrets. It runs for
  both auto and manual `/compact`; its instruction is appended *after* any `/compact` text the user
  typed — additive, never replacing it.
- **PostCompact** receives Claude Code's generated compaction summary and persists it into that
  snapshot as the durable handoff body (flipping `status` to `complete`), so the summary survives
  `/clear`. If compaction skipped PreCompact (reactive prompt-too-long), it creates a completed
  handoff from scratch. If no usable summary arrives, it still completes the snapshot — with an
  explicit "summary unavailable" body over the repo facts — so a handoff the user was told exists
  is never left in a state that hides it.
- **SessionStart** is source-aware: `resume` → no-op (the transcript is already restored);
  `fork` → also silent, but the session inherits its parent's topic (see below); `compact` → a continue-nudge (auto) or a quiet pointer (manual) to the snapshot; `clear` →
  recaps the topic that was just cleared (claimed from a per-directory clear-log) and offers to
  resume, or shows a picker if multiple clears are ambiguous; `startup` → a short list of recent
  topics. It never silently adopts a topic or injects another session's content.
- **SessionEnd(clear)** leaves a small "baton" carrying the cleared session's own topic, so the
  next (new) session can pick it back up. No eager deletion — state is reclaimed by an age sweep.

### Forked sessions

Choosing "Move to background" when exiting, and `--resume … --fork-session`, continue a conversation
under a new session id. The session→topic binding is keyed on that id, so the fork takes over the
binding (and any pending cross-topic links) of the session it continues. The link comes from the
`derived-from` record Claude Code writes near the top of the new transcript, which names the parent
session.

That transcript is not on disk yet when SessionStart fires, so the hook leaves a
`sessions/<sid>.transcript` note holding the time of the fork, the transcript path, and a snapshot
of every session's topic binding at that moment. The parent is resolved the first time the
session's topic is looked up (a save, a resume, a compaction), and its topic is read from the
snapshot. Two consequences:

- The fork gets the topic the conversation was on when it forked. What the parent does afterwards
  (saving again, switching topic, having its state swept) changes nothing.
- A plain resume inherits nothing. It keeps its own session id and binding, and for an old fork
  there is no snapshot from the moment of forking.

The note is removed once a topic is inherited, or once the transcript has had a minute to be
written and names no usable parent. A note that never resolves is swept by age.

A snapshot whose compaction was abandoned before PostCompact ran at all (the process died mid-way)
stays `status: pending` and is hidden from `list`/`resume`. It is inert, not garbage-collected: the
age sweep only ever reclaims *ephemeral state*, never a committed handoff. Delete such a file by
hand if you want it gone.

## Trust boundary

Handoffs are committed files, so their contents can come from a teammate or a branch — they are
**data, not instructions**. `resume` and `load` fence the body between BEGIN/END markers that are
derived per file and guaranteed absent from the body, so a handoff cannot forge the end of its own
fence. Titles and task summaries injected by the hooks are flattened to a single bounded line for
the same reason, and a topic read out of frontmatter is validated as a plain path component before
it is used to build any path — a handoff cannot redirect the plugin to write outside `handoffs/`.

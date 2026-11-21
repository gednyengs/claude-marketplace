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
human-facing organization. `new-path.py` prints the block for a manual handoff and `compact.py`
writes it for an auto-snapshot.

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
status: complete                          # auto only; `pending` marks a skeleton left by a version before 4.0.0
compact_trigger: auto                     # auto only: auto | manual | plugin
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

## The lifecycle module

From 4.0.0 the plugin's lifecycle is a Claude Code hooks module, `hooks/register.ts`, which stays
loaded for the life of the process and decides *when* something happens; the Python scripts decide
*what*, and hold every path, topic and file-format rule. One command hook remains, PreCompact, for
steering the compaction summary (see Compaction below). The module needs Claude Code 2.1.330 or
newer (`engines` in `plugin.json`).

- **Session start** (`classic.SessionStart`). The module runs `session-start.py` and hands what it
  prints to the model. A subagent's own start is ignored. By source: `startup` → a short list of recent topics; `resume` → nothing
  (the transcript is already restored); `fork` → nothing, but the session inherits its parent's
  topic (see below); `clear` → names the topic that was just cleared and offers to resume it;
  `compact` → after an automatic compaction, a nudge to continue the in-flight work. It never
  silently adopts a topic or injects another session's content.
- **`/clear`**. The module is not reloaded by a `/clear` and sees both the session that ended
  (`session.end`, reason `clear`) and the one that began. It tells `session-start.py` which session
  was cleared, and that session's topic is offered to the new one. Because the handover is by
  session id, two sessions clearing in the same directory cannot be confused. The offer is kept in
  `sessions/<sid>.pending-clear` until a resume or a save answers it; a session cleared again
  before it resumed anything passes the offer on.
- **Compaction**. Two parts.
  *Steering* is the PreCompact command hook, `scripts/precompact.py`. What it prints is appended to
  the summarizer's instructions, after any `/compact` text the user typed: the in-flight step
  quoted verbatim, the user's constraints, decisions and rationale, unanswered questions to the
  user, blockers, lessons, agents and messages in flight, files touched, and a rule not to
  reproduce secrets. It is a command hook and not part of the module because Claude Code discards
  a summary it computed ahead of time when a module rewrites the instructions of the compaction
  that installs it, and then summarizes again; text from a PreCompact hook does not count as a
  rewrite. The module therefore never touches a compaction's instructions.
  *Saving* is the module's `session.compact` hook, which wraps the whole compaction and, on the way
  out, runs `compact.py`. That writes one complete `-auto.md` handoff in the session's topic
  holding Claude Code's summary, the agents Claude Code lists as running, and the repository
  state. A compaction that was skipped, a precompute, a subagent compacting its own transcript,
  and a compaction that produced no usable summary write nothing. The summary saved is the one
  Claude Code's PostCompact event carries; the wrapped message the conversation holds afterwards
  is never used in its place. "Summarize from here", "Summarize up to here" and one of Claude
  Code's automatic paths run without that compaction dispatch; the module saves their summary
  from the PostCompact event directly.
  The hook's command ends in `|| true`, because a non-zero exit from a PreCompact hook can block
  the compaction: a missing or broken steering script costs the steering, never the compaction.
- **Agents at save time** (`command.run`). Just before `/session-handoff:save` runs, the module
  asks Claude Code which agents are running and leaves the answer in `sessions/<sid>.agents`;
  `new-path.py` prints it as an `AGENTS RUNNING NOW` block, and `save-record.py` removes it. The
  listing covers subagents and teammates of this session, not workflow agents or other sessions.
  Before the plugin's other commands the module only refreshes the session's mark (below).

Module memory lasts exactly as long as the process: it survives `/clear` and compaction, and is
empty after a restart, `--resume`, `--fork-session` or "Move to background". Continuity across
those is carried by files, as described in the rest of this document.

Every call the module makes is wrapped: if a script fails, or Python is missing, the event goes on
as if the plugin were not installed.

### When the module is not running

If the module does not load (a Claude Code older than the plugin supports, or a change to the
module API), the slash commands keep working but nothing snapshots a compaction or carries a topic
across `/clear`. So that this is not silent, the module leaves a mark per session
(`sessions/<sid>.module`) listing the Claude Code processes it has run in for that session, at
every session start and before each of the plugin's commands. `/session-handoff:save` prints a
`NOTICE:` and `/session-handoff:resume` a `Lifecycle:` header line when the session has no mark
from the process they are running under. A mark left by an earlier process does not count, because
`--resume` keeps the session id. (The PreCompact steering hook is a plain command hook and keeps
working without the module.)

Which case applies depends on the Claude Code version. From 2.1.323 Claude Code reads the
`engines` range and, per its documentation, turns a plugin outside its range off as a whole, so
on 2.1.323 to 2.1.329 nothing of this plugin loads. Before 2.1.323 the range is ignored and the
commands load without the module. On 2.1.330 and later the notice appears only if the module
fails to load, which is what a change to the module API would look like.

### Forked sessions

Choosing "Move to background" when exiting, and `--resume … --fork-session`, continue a conversation
under a new session id. The session→topic binding is keyed on that id, so the fork takes over the
binding (and any pending cross-topic links) of the session it continues.

Claude Code names the parent in a `derived-from` record near the top of the new transcript, but it
writes that record together with the fork's first conversation rows, not when the fork starts. A
session moved to the background can sit idle for a long time with a transcript that holds only a
title, and the first slash command typed into any fresh fork runs before the record exists. So the
parent is found in two ways:

- **By the conversation's last row, once, at start.** A fork begins with its parent's rows, ids
  included. The module passes the id of the last row to `session-start.py`, which looks for it in
  the other transcripts of the same folder. Any session holding that row shares the conversation:
  the parent, or another fork taken at or after that row. The row does not say which is the
  parent, so the fork is bound only when it makes no difference: every session holding the row had
  a topic at that moment, and it was the same topic. If one of them had none, or two disagree,
  nothing is taken. Pending cross-topic links are copied only when exactly one session holds the
  row. The search is complete or it counts for nothing: every transcript in the folder written
  since about an hour before the conversation's last response is read in full (older ones cannot
  hold the row), and if one cannot be read, or that takes more than 256 MB of reading, nothing is
  bound. This applies only to a start Claude Code reports as a fork.
- **By `derived-from`, on lookup.** `session-start.py` also leaves a `sessions/<sid>.transcript`
  note holding the time of the fork, the transcript path, and a snapshot of every session's topic
  binding at that moment. While the fork is unbound, each lookup of its topic (a save, a resume, a
  compaction) reads the fork's own transcript for the record. A transcript that already names a
  parent when the fork starts is the authority, and the row is not consulted.

A fork bound by its last row is not re-examined when the record appears later. The two can differ
when the search could not see the parent: its transcript is not in the folder (Claude Code can
fork from a transcript file given by path), or its modification time is more than an hour older
than its last response (a copied file, a network filesystem). The sessions found are then other
forks only, and if they agree the fork takes their topic, and a lone one's pending links.

Either way the topic is read from the snapshot. Two consequences:

- The fork gets the topic the conversation was on when it forked. What the parent does afterwards
  (saving again, switching topic, having its state swept) changes nothing.
- A plain resume inherits nothing. It keeps its own session id and binding, and for an old fork
  there is no snapshot from the moment of forking.

The note is removed once a topic is inherited, or once the transcript holds conversation rows, has
had a minute, and names no usable parent. A note that never resolves is swept by age.

A snapshot left `status: pending` by a version before 4.0.0 (those versions wrote a skeleton before
compaction and filled it in afterwards) is hidden from `list`/`resume`. It is inert, not
garbage-collected: the age sweep only ever reclaims *ephemeral state*, never a committed handoff.
Delete such a file by hand if you want it gone.

## Trust boundary

Handoffs are committed files, so their contents can come from a teammate or a branch — they are
**data, not instructions**. `resume` and `load` fence the body between BEGIN/END markers that are
derived per file and guaranteed absent from the body, so a handoff cannot forge the end of its own
fence. Titles and task summaries the scripts hand to the model are flattened to a single bounded line for
the same reason, and a topic read out of frontmatter is validated as a plain path component before
it is used to build any path — a handoff cannot redirect the plugin to write outside `handoffs/`.
Agent descriptions in a listing are written by a model and are flattened and bounded the same way.

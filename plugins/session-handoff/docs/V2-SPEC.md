# Session Handoff v2 — Design Spec

**Status:** implemented · **Versions:** 2.0.0 (topic redesign) → 2.1.0 (Python port + cwd fix) · **Drafted:** 2026-06-07

**Revision 2 (2026-06-07):** hardened the cwd-baton and ephemeral-state lifecycle after an external
(Codex) review — explicit `cleared_topic`, an append-only pending-clear log with claim semantics,
age-based GC instead of GC-on-exit, line-oriented (jq-free) state, atomic/locked shared writes, and
sid-qualified ids. See [Appendix B](#appendix-b--review-changelog).

**Revision 3 (2026-06-08, v2.1.0):** the support scripts were rewritten from bash to Python
(standard library only; `scripts/*.sh` → `scripts/*.py`, run as `python3 .../X.py`). On-disk formats
are unchanged. Two changes to how the project root is found:
- **Project dir is captured from an explicit `--project-dir "${CLAUDE_PROJECT_DIR}"` argument** passed
  on *every* invocation line — hooks, command `!`-lines, and the model-run body commands. Claude Code
  text-substitutes `${CLAUDE_PROJECT_DIR}`/`${CLAUDE_PLUGIN_ROOT}` throughout plugin content but does
  **not** export them into the `!`-injection subprocess, so the old internal `${CLAUDE_PROJECT_DIR:-$(pwd)}`
  env lookup fell back to a drifted `pwd` and wrote artifacts under a subdirectory. There is no
  env/walk-up/git/pwd recovery: a missing value errors in command scripts and is a no-op in hooks.
- **State dir is resolved identically** via a uniform `--plugin-data "${CLAUDE_PLUGIN_DATA}"` so
  ephemeral state can't split between out-of-repo and in-repo across hook vs. command contexts.

Because the scripts are Python, **`jq` is no longer used** (`json` parses hook stdin and `package.json`);
the §1 "graceful degradation" note about `jq` and the §2/§3 "jq-free" remarks now refer to the design
intent (line-oriented state), satisfied natively by the stdlib.

This spec defines the topic-based redesign of the session-handoff plugin. It is grounded in
empirically verified Claude Code session-lifecycle behavior (see [Appendix A](#appendix-a--verified-lifecycle-facts)).

---

## 1. Goals & motivation

v1 keys handoffs on the Claude Code `session_id`. That breaks across `/clear`, which starts a
**new** session id, severing the link between a workstream's sessions. v2 reorganizes around a
**topic** — a thread of work that spans many sessions (across `/clear`, restarts, compaction,
and teammates) — so continuity survives the things that rotate the session id.

Design principles carried over from v1 (do not regress):

- **Low always-on cost** — touch context only at the moments it's at risk.
- **Deterministic first, model second** — shell scripts gather ground truth; the model fills judgment.
- **No shared mutable committed state** — every session writes only its own timestamped files;
  any index is *regenerable*, never authoritative. This is what keeps concurrent sessions safe.
- **Graceful degradation** — `jq` optional (ephemeral state is line-oriented, not JSON); missing
  ephemeral state falls back to a picker, never an error.

---

## 2. Concepts

| Term | Meaning |
|---|---|
| **Topic** | A named thread of work spanning ≥1 session. The unit of continuity. Stable kebab-case slug + human title. |
| **Handoff** | A markdown file capturing resumable context. Either **manual** (`/save`) or **auto** (pre-compaction snapshot). |
| **Session** | One Claude Code `session_id`. A session belongs to at most one topic (acquired lazily). |
| **cwd** | The project directory. The only correlator that survives `/clear` (verified — no parent id exists). |

A session acquires its topic **lazily** — on the first `/resume`, `/load`, `/save`, or auto-snapshot —
and records it. Topics are otherwise implicit; users rarely name them by hand.

---

## 3. On-disk layout

### 3.1 Committed artifacts (in the project tree)

```
.claude/sekekama/session-handoff/
└── handoffs/
    └── <topic-slug>/
        ├── 2026-06-07-115447-d8bcd36b.md         # manual handoff
        └── 2026-06-07-120130-d8bcd36b-auto.md    # pre-compaction snapshot
```

- Topic subdirectories are **human-facing organization only**. The authoritative topic of a file is
  its frontmatter `topic:` — a misfiled file is still correctly attributed.
- Filenames sort chronologically (`YYYY-MM-DD-HHMMSS` prefix) and are session-tagged to avoid
  collisions between concurrent sessions.

### 3.2 Ephemeral state (out of the repo)

Lives in `CLAUDE_PLUGIN_DATA` (never committed). Fallback if unset: `.claude/sekekama/session-handoff/.state/`
(the plugin writes a `.gitignore` containing `*` into `.state/` so it can never be tracked).

**All ephemeral files are line-oriented `key=value` (or TAB-delimited records) — never JSON — so the
plugin never depends on `jq`** (carries the v1 graceful-degradation guarantee). All writes are atomic
(temp file + `mv`); the append-only `.clears` log and any read-modify-write on `.ptr` are serialized
with a per-cwd `flock` (best-effort; absent `flock`, per-sid keying already removes cross-session
contention).

```
$CLAUDE_PLUGIN_DATA/
├── sessions/
│   ├── <sid>.topic           # one line: the topic slug (the session→topic mapping)
│   ├── <sid>.deps            # cross-topic handoff ids, one per line (pending → next /save)
│   ├── <sid>.pending-clear   # one line: "<cleared_topic>\t<cleared_sid>\t<cleared_at_ms>" (claimed baton)
│   └── <sid>.compact         # 2 lines: "trigger=auto|manual" / "ts=<ms>" (consume-once per compaction)
├── cwd/
│   ├── <cwd-hash>.ptr        # key=value: topic / last_sid / updated_at  (the durable pointer)
│   └── <cwd-hash>.clears     # append-only TAB log; 1 line per /clear: ts \t cleared_sid \t cleared_topic \t claimed_by
└── enforce.<sid>.count       # Stop-hook nudge counter (unchanged from v1)
```

`<cwd-hash>` = first 16 hex of `sha1(cwd)` (stable per directory).

All of this state is reclaimed by an **age-based GC sweep** (§8.5), not by eager deletion on exit —
which is what makes it correct across `--resume` and crash/kill.

### 3.3 Commit posture: **neutral**

The plugin writes artifacts and lets the project's own `.gitignore` decide what is tracked. It does
**not** edit `.gitignore` or force tracking. On first write it emits a one-time notice. The README
documents the caveat: **git cannot re-include a subtree under a wholesale-ignored `.claude/`** — to
track handoffs, a project must ignore `.claude/` granularly (e.g. only `settings.local.json`), not as
a whole. Ephemeral state lives outside the repo, so tracking-or-not is always safe.

---

## 4. Frontmatter schema

Every handoff begins with YAML frontmatter (the source of truth; model-written, not jq-parsed):

```yaml
---
schema: 2                       # spec version, for migration
topic: auth-refactor            # stable slug
topic_title: "Auth refactor"    # human title (may be refined later without renaming the slug)
session_id: d8bcd36b            # originating session (provenance + collision-avoidance)
created: 2026-06-07T11:54:47-07:00
kind: manual                    # manual | auto
note: "before the token-rotation rework"   # optional one-line label the writer may add (not the /save note)
depends_on:                     # cross-topic refs only (intra-topic chain is implicit)
  - billing-export/2026-06-01-101500-x9y8
compact_trigger: auto           # auto snapshots only: auto | manual (provenance)
---
```

Body sections: Task & progress · Key decisions & rationale · Open questions & blockers · Next steps ·
Environment, commands & results · Repo snapshot · Resume instructions, plus an optional
"Approaches tried & dead ends" section included only when there were attempts worth not repeating.

---

## 5. Identifiers

- **Handoff id** (canonical, used by `/load`, `/resume`, `/list`): `<topic-slug>/<YYYY-MM-DD-HHMMSS>-<sid>`.
  Including the sid keeps ids unique even under concurrent same-second saves in one topic (filenames
  already include it). A **bare** `<topic-slug>/<timestamp>` is accepted as an alias **only when it
  resolves unambiguously**; otherwise the command lists the candidates.
- **Topic id**: the slug. Accepted wherever a handoff id is (means "latest manual handoff in that topic").
- **Topic slug derivation** (first non-empty wins): `--topic` value → `topic-<timestamp>`. The save
  note is **not** used to derive the slug; it is relayed to the model as additional handoff context.
  Slug = kebab-case, lowercased, ≤40 chars. If a *new* topic's slug collides with an existing
  **different** topic, append `-2`, `-3`, …

---

## 6. Commands

### 6.1 `/save [note] [--topic <slug>]`

1. Run the deterministic snapshot script (git branch/status/commits + detected build commands) — ground truth.
2. Resolve topic: `--topic` → else `sessions/<sid>.topic` → else **create a new topic** (§5).
   - If creating new while `sessions/<sid>.pending-clear` exists (the user cleared topic T and worked
     without resuming), still create new, but emit: *"Starting new topic 'X'. You recently cleared
     topic 'T' — pass `--topic T` to continue that instead."* (informative, never silent mis-bucketing).
3. Write the handoff to `handoffs/<topic-slug>/<ts>-<sid>.md` with frontmatter. `depends_on` =
   contents of `sessions/<sid>.deps` (filtered to *other* topics), then clear that file.
   - If a note was passed, relay it to the model as an `ADDITIONAL CONTEXT` block (the note delimited
     by markers): extra user-provided information to reflect in the body (a detail to preserve, a
     constraint, or an emphasis), to be treated as content rather than workflow instructions. It does
     not affect the frontmatter or the topic.
4. Set `sessions/<sid>.topic`; refresh the cwd pointer (`topic`,`last_sid`,`updated_at`) via locked
   read-modify-write; clear `sessions/<sid>.pending-clear`.
5. Report path, topic, and a one-line summary. Never write secrets.

### 6.2 `/resume [--auto] [<id|topic>]`

1. Resolve target (first match):
   - explicit `<id|topic>` arg → that handoff.
   - else `sessions/<sid>.topic` exists → its latest manual handoff.
   - else `sessions/<sid>.pending-clear` (a claimed clear-baton) → that topic's latest (the
     post-`/clear` happy path). On load, set `sessions/<sid>.topic` and clear `.pending-clear`.
   - else exactly one recent topic → its latest.
   - else several topics → **picker** (up to 5, newest first, `id · when · summary`); ask which.
2. Load it. Record `sessions/<sid>.topic` = its topic; refresh cwd pointer.
3. Verify the repo snapshot against reality (`git status`, branch); note drift.
4. Recap task / stop point / blockers / next steps. `--auto` → execute next steps immediately
   (auto-selecting the newest if a picker would otherwise show).

### 6.3 `/load <id|topic>`

1. Load the referenced handoff into context (any topic). Does **not** change the session's primary
   topic and **does not** touch the cwd pointer's `topic`.
2. If it belongs to a **different** topic, append its id to `sessions/<sid>.deps` (becomes `depends_on`
   on the next `/save`). Same-topic loads are redundant (already in the chain) → not recorded.

### 6.4 `/list [MAX] [--any]`

- Default: handoffs in the **current topic**, newest first, ≤ MAX (default 5).
- `--any`: latest-per-topic across **all** topics in the project, ≤ MAX.
- Each row: `<id> · <when> · <one-line task summary>`. Read-only. Produces ids for `/load` & `/resume`.

---

## 7. cwd pointer & clear bridge

Two per-cwd artifacts (line-oriented, locked, atomic):

**`<cwd-hash>.ptr`** — the durable "active topic here" pointer.

```
topic=auth-refactor
last_sid=d8bcd36b
updated_at=1780864460407
```

- Refreshed on **`/resume` and `/save` only** (NOT `/load`, which never changes the primary topic).
- A hint, not authority: any referenced topic/handoff is validated before use; a dangling pointer is
  treated as absent.

**`<cwd-hash>.clears`** — an append-only log of `/clear` events (one TAB-delimited line each):

```
<ts_ms>\t<cleared_sid>\t<cleared_topic>\t<claimed_by|->
```

- **Written by `SessionEnd(reason=clear)`** (§8.2), which reads the **clearing session's own**
  `sessions/<cleared_sid>.topic` to fill `cleared_topic` — *independent of the shared pointer*, so a
  concurrent session's topic can't be mis-attributed. `claimed_by` starts `-`.
- **Claimed by `SessionStart(source=clear)`** (§8.1) under `flock`: among entries that are
  **unclaimed AND fresh** (`ts` within a freshness window, default 120 s):
  - exactly **1** → claim it (set `claimed_by=<new_sid>`), copy its `cleared_topic` into
    `sessions/<new_sid>.pending-clear`, and inject a suggestion for that topic.
  - **≥2** → ambiguous (concurrent clears in this cwd) → claim none, inject the multi-topic picker.
  - **0** → inject the startup-style topic list.

  Because the post-`/clear` session has no correlator to the old sid (verified), it claims by
  recency, not by sid — which is exactly why ≥2 fresh unclaimed entries are ambiguous.
- **Consume-once**: claiming flips `claimed_by`, so the baton can never be re-adopted by an unrelated
  later session. The topic now lives in the *session-private* `.pending-clear`, decoupled from whether
  the user actually resumes.
- **Suggest, never adopt**: claiming does **not** set `sessions/<sid>.topic`. The session acquires the
  topic only when the user `/resume`s (which reads `.pending-clear`). If they ignore the suggestion
  and just work, the first `/save` creates a new topic with the informative notice in §6.1.
- **Future hardening**: if Claude Code adds `previous_session_id` to `SessionStart(source=clear)`
  (feature request filed), claim by exact sid instead of recency — eliminating the ambiguity entirely.
  Drop-in.

---

## 8. Hooks

### 8.1 SessionStart — branch on `source` (all verified)

| `source` | sid | Action |
|---|---|---|
| `resume` | same | **No-op.** The CLI already restored the full transcript; re-injection is redundant. |
| `compact` | same | Read `sessions/<sid>.compact` marker. **auto** → inject a *concise* nudge: "auto-compaction occurred mid-task; snapshot at `<path>` (next steps: …); continue your in-flight work." **manual** (or marker missing) → light touch: at most a one-line pointer to the snapshot; no continue-nudge. Consume the marker. |
| `clear` | **new** | Claim from `<cwd-hash>.clears` per §7: 1 fresh → recap topic T (title · last task line · next step) + offer `/resume`; ≥2 → topic picker; 0 → topic-title list. Never silently adopt. |
| `startup` | new | Inject a bounded list of recent **topic titles** + pointer to `/resume`. No auto-load. |

Output is always byte-capped to keep per-turn cost near zero. Opportunistically runs the age sweep (§8.5).

### 8.2 SessionEnd — branch on `reason` (cleanup only; not blockable)

| `reason` | Action |
|---|---|
| `clear` | Read `sessions/<cleared_sid>.topic`; append a `<cwd-hash>.clears` entry `{ts, cleared_sid, cleared_topic, claimed_by=-}` under `flock`. **Do not** delete the session's `.topic`/`.deps` — a cleared session is still `--resume`-able under its old sid, and eager deletion would orphan it. |
| `prompt_input_exit` / `logout` / `other` | **No eager deletion.** `.topic`/`.deps` are retained so a later `--resume` (same sid) still knows its topic for `/save`. Reclamation is age-based (§8.5). |

> Rationale: `--resume` keeps the **same** session_id (verified), so GC-on-exit would make a resumed
> session forget its topic and mis-bucket the next `/save`. All reclamation is deferred to the age sweep.

### 8.3 PreCompact

1. Write the deterministic auto-snapshot (git+env facts + `<!-- TODO -->` placeholders) to the
   session's topic dir. If the session has no topic yet, create a **provisional** topic
   `topic-<timestamp>`, record it in `sessions/<sid>.topic`, and write there.
2. Stash `sessions/<sid>.compact` = `trigger=<auto|manual>` + `ts=<ms>` (SessionStart(compact) can't
   otherwise tell auto from manual — verified).
3. Inject the enrichment nudge — emphasizing the **in-flight step** (half-applied edit, the next
   command), not just a retrospective summary, so an auto-continue resumes mid-stride.

**Provisional-topic rule:** a provisional topic is *kept as-is* — the session's later first `/save`
**joins the same provisional slug** (no directory rename, no frontmatter rewrite, no risk of orphaning
the auto-snapshot). `topic_title` may still be set to something human in the `/save`. (Renaming a slug
mid-stream is explicitly out of scope; the slug is cosmetic, the title carries readability.)

> Note: during a long auto-continuing task the agent may not pause to enrich the snapshot. That's
> acceptable — the deterministic snapshot carries facts, and the Stop hook enforces TODO-filling when
> the turn finally ends.

### 8.4 Stop (unchanged from v1)

If this session's own latest auto-snapshot still has `<!-- TODO -->` markers, nudge to fill it —
session-scoped, capped at 2 attempts via `enforce.<sid>.count`.

### 8.5 Age-based GC & crash recovery

A single idempotent sweep, invoked opportunistically (throttled, e.g. once per process via a
timestamp guard) from SessionStart and the command scripts:

- Delete `sessions/<sid>.*`, `enforce.<sid>.count`, and `<cwd-hash>.clears` lines older than a TTL
  (default 14 days; configurable). This reclaims everything a crash/kill (no `SessionEnd`) leaves behind.
- Validate referenced handoff paths before trusting a pointer/baton; treat dangling references as absent.
- The sweep never touches committed handoffs — only ephemeral state.

---

## 9. Migration (v1 → v2)

Must be **idempotent** and **safe under partial failure**:

1. Trigger when legacy `.handoff/*.md` exists. Run at most once (guard with a `.migrated` marker).
2. **Copy** (not move) each legacy handoff into `.claude/sekekama/session-handoff/handoffs/legacy/`,
   synthesizing minimal frontmatter (`schema: 2`, `topic: legacy`, `kind` from the `-auto` suffix,
   `session_id` from the filename tag if present).
3. Only after **all** target writes succeed: write the `.migrated` marker and leave a tombstone
   `README` in `.handoff/` pointing to the new location. The legacy files are left in place (copy, not
   move) so a partial/aborted run never loses data; a second run is a no-op.

grill-to-plan moves analogously (`.claude/specs/<feature>/` → `.claude/sekekama/grill-to-plan/specs/<feature>/`)
under its own major bump — tracked separately from this spec.

---

## 10. Concurrency & safety properties

- Each session writes only its **own** timestamped, sid-tagged handoff files → no write contention,
  no merge conflicts. (`/save` from two concurrent sessions never touches the same file; ids are
  sid-qualified so they don't collide either.)
- Topic grouping derives from **frontmatter**, so any subdir/manifest view is regenerable; a stale or
  missing index is never load-bearing.
- Shared per-cwd state (`.ptr`, `.clears`) is updated only via **locked, atomic read-modify-write**
  that preserves fields it doesn't own.
- Ephemeral state is keyed per-sid (maps, markers, counters, pending-clear) or per-cwd (pointer/clears
  log), lives outside the repo, and is reclaimed by age → no session can block or contaminate another,
  crash leaks self-heal, and nothing leaks into commits.
- The one inherent ambiguity — concurrent `/clear`s in the same cwd — is **detected** (≥2 fresh
  unclaimed clear entries) and degrades to the picker.

---

## 11. Open sub-decisions (defaults chosen; confirm or adjust)

1. **Legacy migration** lumps all v1 files into a single `legacy` topic (vs one topic per old session). *Default: single `legacy` topic.*
2. **Post-clear-without-resume `/save`** creates a new topic + informative notice (vs silently adopting the claimed baton topic). *Default: new topic + notice.*
3. **Freshness window** for claiming a clear-baton = 120 s; **age-GC TTL** = 14 days. *Defaults; both configurable.*
4. **Provisional topics** are never renamed; the first `/save` joins the provisional slug. *Default as written.*
5. **Spec doc location** = `plugins/session-handoff/docs/V2-SPEC.md`. *Move if you prefer elsewhere.*

---

## Appendix A — verified lifecycle facts

Empirically confirmed via an instrumented hook probe (2026-06-07):

| Operation | session_id | Hooks |
|---|---|---|
| `/compact` (manual) | **same** | `PreCompact trigger=manual` → `SessionStart source=compact` |
| auto-compaction | **same** | `PreCompact trigger=auto` → `SessionStart source=compact`; **agent auto-continues its in-flight task** (1 UserPromptSubmit, 0 Stop across 3 compaction cycles) |
| `/clear` | **NEW** | `SessionEnd reason=clear` (old sid) → `SessionStart source=clear` (new sid), ~20 ms apart |
| `--resume`/`--continue` | **same** | `SessionStart source=resume` |
| Ctrl-D / exit | — | `SessionEnd reason=prompt_input_exit` |

- transcript basename == session_id (only "rotates" when the sid genuinely changes).
- The `SessionEnd(clear)` and `SessionStart(clear)` payloads share **no** correlator except `cwd`.
- `SessionStart(compact)` carries **no** auto/manual field → must read it from the PreCompact marker.

## Appendix B — review changelog

External review (Codex, 2026-06-07) returned GO-WITH-CHANGES. Rev 2 incorporates all findings:

- **Baton topic provenance** — baton now carries an explicit `cleared_topic` read from the clearing
  session's own `.topic`, not the shared pointer (was: wrong-topic suggestion under concurrency).
- **Concurrent-clear detection** — single overwritten record replaced by an append-only `.clears` log;
  ≥2 fresh unclaimed entries ⇒ ambiguous ⇒ picker (was: not actually detectable).
- **Consume-once** — `SessionStart(clear)` claims into `.pending-clear` and flips `claimed_by`
  (was: baton stayed fresh indefinitely, adoptable by an unrelated session).
- **GC vs `--resume`** — no eager GC on `SessionEnd`; age-based sweep instead (was: resumed/cleared
  sessions forgot their topic and mis-bucketed the next `/save`).
- **Id uniqueness** — canonical id is sid-qualified `<topic>/<ts>-<sid>` (was: same-second collisions).
- **`/load` & pointer** — `/load` records only `.deps`, never the pointer topic.
- **Atomicity** — `.ptr`/`.clears` updated via locked atomic read-modify-write preserving other fields.
- **jq-free** — ephemeral state is line-oriented `key=value`/TAB, not JSON.
- **Provisional topics** — kept as-is; first `/save` joins the provisional slug (no rename/orphan).
- **Migration** — idempotent, copy-before-delete, abort-on-partial.

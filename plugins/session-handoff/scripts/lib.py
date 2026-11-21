#!/usr/bin/env python3
# Shared helpers for the session-handoff plugin, imported by the command and
# hook scripts.
#
# Conventions:
#   - Hook entry points run their body via run_hook(): unexpected errors are
#     swallowed and the process exits 0, so a hook can never abort the session.
#   - The project directory is read from --project-dir; the state directory from
#     --plugin-data, else an in-repo .state/ directory.
#   - Ephemeral state is line-oriented (key=value / TAB) and written atomically
#     (temp file + os.replace). Per-directory locking is best-effort.
#   - Committed handoffs live under <project>/.claude/sekekama/session-handoff/.

import glob
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime

try:
    import fcntl
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - non-Unix
    _HAVE_FCNTL = False

# A value that still looks like an unsubstituted Claude Code token (a failed
# substitution), e.g. "${CLAUDE_PROJECT_DIR}". NOT merely any "$" — a legit path
# may contain "$".
_TOKEN_RE = re.compile(r"^\$\{CLAUDE_[A-Z_]+\}$")

TS_RE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}"   # sortable timestamp prefix

# Resolved once per process by init_context()/bootstrap().
_CTX = {"project_dir": None, "state_dir": None}


# --- Bootstrap: resolve project dir & state dir from leading trusted flags --

def split_leading_flags(argv):
    """Consume the leading trusted --project-dir / --plugin-data flags from the
    front of argv (the plugin-authored prefix). Each is taken AT MOST ONCE, so a
    later occurrence inside user arguments cannot redefine the trusted value;
    parsing also stops at the first non-flag token or an explicit `--`.

    Returns (project_dir, plugin_data, rest)."""
    project = None
    plugin_data = None
    i, n = 0, len(argv)
    while i < n:
        a = argv[i]
        if a == "--":                       # explicit end of the trusted prefix
            i += 1
            break
        if project is None and a == "--project-dir" and i + 1 < n:
            project = argv[i + 1]; i += 2; continue
        if project is None and a.startswith("--project-dir="):
            project = a[len("--project-dir="):]; i += 1; continue
        if plugin_data is None and a == "--plugin-data" and i + 1 < n:
            plugin_data = argv[i + 1]; i += 2; continue
        if plugin_data is None and a.startswith("--plugin-data="):
            plugin_data = a[len("--plugin-data="):]; i += 1; continue
        break                               # first non-trusted token: stop
    return project, plugin_data, argv[i:]


def _fail(msg, strict):
    if strict:
        sys.stderr.write("error: " + msg + "\n")
        sys.exit(1)
    return None


def resolve_project_dir(arg, *, strict=True):
    """Resolve the project directory from the --project-dir argument.

    Returns an absolute, normalized path. In strict mode an empty or invalid
    value exits with an error; in non-strict (hook) mode it returns None."""
    val = (arg or "").strip()
    if not val or _TOKEN_RE.match(val):
        return _fail("missing --project-dir (CLAUDE_PROJECT_DIR was not provided)", strict)
    p = os.path.normpath(os.path.abspath(val))   # normalizes, strips trailing slash; NO realpath
    if not os.path.isdir(p):
        return _fail("--project-dir is not a directory: " + val, strict)
    return p


def _resolve_state_dir(plugin_data_arg, project_dir):
    """State dir = --plugin-data if it's a valid (non-token) value, else the
    in-repo .state/ under the project. Resolved consistently across all caller
    contexts so ephemeral state can never split."""
    val = (plugin_data_arg or "").strip()
    if val and not _TOKEN_RE.match(val):
        return os.path.normpath(os.path.abspath(val))
    return os.path.join(project_dir, ".claude", "sekekama", "session-handoff", ".state")


def init_context(project_dir_arg, plugin_data_arg=None, *, strict=True):
    """Resolve and store the project dir + state dir. Returns True on success,
    False when (non-strict) the project dir couldn't be resolved."""
    pd = resolve_project_dir(project_dir_arg, strict=strict)
    if pd is None:
        return False
    _CTX["project_dir"] = pd
    _CTX["state_dir"] = _resolve_state_dir(plugin_data_arg, pd)
    _GIT_DEADLINE[0] = None
    return True


def bootstrap(argv, *, strict):
    """Parse leading trusted flags and init the context. Returns (ok, rest)."""
    project, plugin_data, rest = split_leading_flags(argv)
    ok = init_context(project, plugin_data, strict=strict)
    # Paths and titles can carry bytes that are not valid text in the terminal's
    # encoding. Printing must never be what makes a command fail.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass
    return ok, rest


def run_hook(body):
    """Run a hook body so an unexpected error can NEVER abort the session.
    Catches unexpected exceptions only — intended output (prints, block
    decisions) has already been emitted by then. Always exits 0."""
    try:
        body()
    except SystemExit:
        raise
    except BaseException:
        pass
    sys.exit(0)


# --- Project & committed paths ----------------------------------------------

def project_dir():
    return _CTX["project_dir"]


def root():
    return os.path.join(project_dir(), ".claude", "sekekama", "session-handoff")


def handoff_dir():
    return os.path.join(root(), "handoffs")


# A topic slug is the only untrusted value interpolated into a handoff path, and
# it can arrive from places we do not control: a committed handoff's frontmatter,
# a --topic argument, a baton written by an earlier session. Restrict it to a
# single safe path component. The grammar forbids a leading dot and any path
# separator, so a slug can never traverse ("../x"), absolutize ("/tmp/x", which
# os.path.join would silently let swallow the base), or name "." / "..".
# fullmatch, NOT match: Python's `$` also matches just before a trailing newline,
# so `^...$` would accept "safe\n" — a value that then reaches a path or a
# frontmatter line as two lines. The grammar must mean exactly what it says.
_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def valid_slug(slug):
    return bool(_SLUG_RE.fullmatch(slug or ""))


def safe_slug(slug, fallback=""):
    """Return `slug` if it is a well-formed topic slug, else `fallback` (itself
    validated), else "". Use wherever an untrusted topic enters the plugin."""
    if valid_slug(slug):
        return slug
    return fallback if valid_slug(fallback) else ""


def topic_dir(slug):
    """Path of a topic directory. Raises on a malformed slug — callers that may
    hold untrusted input must launder it through safe_slug() first."""
    if not valid_slug(slug):
        raise ValueError("invalid topic slug: %r" % (slug,))
    return os.path.join(handoff_dir(), slug)


def legacy_dir():
    return os.path.join(project_dir(), ".handoff")


# --- Ephemeral state paths --------------------------------------------------

def state_dir():
    return _CTX["state_dir"]


def sessions_dir():
    return os.path.join(state_dir(), "sessions")


def cwd_dir():
    return os.path.join(state_dir(), "cwd")


_INREPO_STATE_SUFFIX = os.path.join(".claude", "sekekama", "session-handoff", ".state")


def ensure_state():
    d = state_dir()
    try:
        os.makedirs(os.path.join(d, "sessions"), exist_ok=True)
        os.makedirs(os.path.join(d, "cwd"), exist_ok=True)
    except OSError:
        pass
    # Guard the in-repo fallback so it can never be tracked.
    if d.endswith(_INREPO_STATE_SUFFIX):
        gi = os.path.join(d, ".gitignore")
        if not os.path.exists(gi):
            try:
                with open(gi, "w") as f:
                    f.write("*\n")
            except OSError:
                pass


# --- Time -------------------------------------------------------------------

def timestamp():
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")           # sortable filename stamp


def iso():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")   # human stamp


def created_stamp():
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")    # ISO + numeric tz (no colon)


def now_ms():
    return int(time.time() * 1000)


# --- Session identity -------------------------------------------------------

def _load_payload(payload):
    if not payload:
        return None
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return None


def session_id(payload=None):
    """Resolve the session id. payload (optional) = raw hook stdin JSON."""
    sid = ""
    data = _load_payload(payload)
    if data is not None:
        sid = data.get("session_id") or ""
        if not sid:
            tp = data.get("transcript_path") or ""
            if tp:
                base = os.path.basename(tp)
                sid = base[:-6] if base.endswith(".jsonl") else base
    if not sid:
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not sid:
        sid = "nosession"
    return sid


def short_id(full):
    """Filename-safe short form of a session id: up to 12 alphanumerics."""
    return re.sub(r"[^a-zA-Z0-9]", "", full or "")[:12]


def session_short(payload=None):
    """Filename-safe short id: up to 12 alphanumerics. THE identity key."""
    return short_id(session_id(payload))


def session_is_degraded(sid):
    return sid == "nosession"


def payload_field(payload, field):
    """A hook payload's source/reason/trigger (best-effort)."""
    data = _load_payload(payload)
    if data is None:
        return ""
    v = data.get(field)
    return "" if v is None else str(v)


# --- Generic atomic / locked writes -----------------------------------------

def _atomic_write_bytes(dest, data):
    """Atomically publish raw bytes to `dest` (temp in same dir, then replace).
    Returns True on success, False if even the non-atomic fallback failed."""
    d = os.path.dirname(dest) or "."
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".hb.", dir=d)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        return True
    except OSError:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass
    try:                                    # last-resort non-atomic fallback
        with open(dest, "wb") as f:
            f.write(data)
        return True
    except OSError:
        return False


def atomic_write(dest, content):
    """Atomically write text `content` (UTF-8) to `dest`. Returns True on success."""
    return _atomic_write_bytes(dest, content.encode("utf-8", "surrogateescape"))


def atomic_write_bytes(dest, data):
    """Atomically write raw bytes to `dest`. Returns True on success."""
    return _atomic_write_bytes(dest, data)


def with_lock(lockfile, func, *args, **kwargs):
    """Run func while holding an exclusive lock on lockfile (best-effort; a
    no-op lock when fcntl is unavailable — per-sid/per-cwd keying already
    removes most contention)."""
    d = os.path.dirname(lockfile) or "."
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    if not _HAVE_FCNTL:
        return func(*args, **kwargs)
    fh = None
    try:
        fh = open(lockfile, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except OSError:
        pass
    try:
        return func(*args, **kwargs)
    finally:
        if fh is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()


# --- Line-oriented key=value state ------------------------------------------

def kv_get(path, key):
    if not os.path.isfile(path):
        return ""
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(key + "="):
                    return line[len(key) + 1:].rstrip("\n")
    except OSError:
        pass
    return ""


def kv_set(path, key, value):
    """Read-modify-write preserving other keys. Returns True on success."""
    lines = []
    if os.path.isfile(path):
        try:
            with open(path) as f:
                lines = [ln for ln in f.read().split("\n")
                         if ln and not ln.startswith(key + "=")]
        except OSError:
            lines = []
    lines.append("%s=%s" % (key, value))
    return atomic_write(path, "\n".join(lines) + "\n")


# --- Session->topic map and per-session state -------------------------------

def session_topic_file(sid):
    return os.path.join(sessions_dir(), sid + ".topic")


def _topic_read(sid):
    try:
        with open(session_topic_file(sid)) as f:
            return f.read()
    except OSError:
        return ""


def session_topic_get(sid):
    """The topic a session is bound to, or "". A forked session that has not
    resolved its parent yet does so here, on first use (see "Forked sessions")."""
    return _topic_read(sid) or _inherit_pending(sid)


def session_topic_set(sid, topic):
    """Bind a session to a topic. Returns True on success — callers on a command
    path must report a failure rather than claim the save was recorded."""
    ensure_state()
    return atomic_write(session_topic_file(sid), topic)


# --- Forked sessions --------------------------------------------------------
#
# Some operations continue a conversation under a NEW session id: choosing "Move
# to background" when exiting, and `--resume ... --fork-session`. Everything here
# is keyed on the session id, so without help the continuation would have no
# topic and its next save would open a new one. Claude Code records the link in
# the new session's transcript:
#     {"type":"derived-from","sessionId":"<new>","sessions":[{"id":"<parent>","via":"fork"},...]}
# This is a Claude Code format we do not control. If it changes, parent_sessions()
# finds nothing and behavior falls back to what it was before: no inherited topic.
#
# Timing matters: when SessionStart fires for the fork, that transcript has not
# been written yet (observed on 2.1.330 — the file appears about a second later).
# So the hook only notes the fork (note_fork: when it happened, and where the
# transcript will be), and the parent is resolved the first time anything asks
# for the session's topic.
#
# What is inherited is the topic the conversation was on WHEN IT FORKED. The note
# therefore carries a snapshot of every session's binding at that moment: once the
# transcript names the parent, the answer is read from the snapshot, not from the
# parent's state as it is by then. A parent that later switches topic, saves again,
# or has its state swept changes nothing. Nothing is inherited on a later plain
# resume, when no snapshot from the moment of the fork exists.

_DERIVED_SCAN_BYTES = 2 * 1024 * 1024     # the record sits near the top of the file
_INHERITED_STATE = (".deps", ".pending-clear")
_FORK_VIA = ("fork", "resume")            # the derivations observed for a continued session
_FORK_SLACK_S = 10                        # hook ordering and clock granularity around the fork
_FORK_SETTLE_S = 60                       # how long Claude Code gets to write the transcript head
_SNAPSHOT_MAX = 2000


def parent_sessions(transcript_path, sid):
    """Short ids of the sessions `sid` was derived from, nearest first, read from
    the `derived-from` records in its transcript. [] when there are none. Reads a
    bounded prefix of a regular file and nothing else."""
    groups = []
    try:
        if not stat.S_ISREG(os.stat(transcript_path).st_mode):
            return []
        with open(transcript_path, "rb") as f:
            budget = _DERIVED_SCAN_BYTES
            while budget > 0:
                raw = f.readline(budget)    # never more than the remaining budget
                if not raw:
                    break
                budget -= len(raw)
                if b'"derived-from"' not in raw:
                    continue
                try:
                    rec = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if (isinstance(rec, dict) and rec.get("type") == "derived-from"
                        and short_id(str(rec.get("sessionId", ""))) == sid):
                    sessions = rec.get("sessions")
                    groups.append([short_id(x["id"]) for x in (sessions if isinstance(sessions, list) else [])
                                   if isinstance(x, dict) and isinstance(x.get("id"), str)
                                   and x.get("via") in _FORK_VIA])
    except OSError:
        return []
    out = []
    for ids in reversed(groups):            # a later record is a nearer ancestor
        for pid in ids:
            if pid and pid != sid and pid != "nosession" and pid not in out:
                out.append(pid)
    return out


def inherit_from_parent(sid, transcript_path, topics=None, forked_at=None):
    """Give a forked session the topic binding (and pending links) of the session
    it continues. Returns the inherited topic, or "" if there was nothing to
    inherit. Never overwrites state the session already has.

    `topics` is the {session: topic} snapshot taken when the fork happened; without
    it the parents' current bindings are read. Ids from the transcript are reduced
    to plain alphanumerics by short_id() before they are used as a key or in a
    filename, and the topic is validated like any other."""
    if not sid or session_is_degraded(sid) or not transcript_path:
        return ""
    if safe_slug(_topic_read(sid)):
        return ""
    for parent in parent_sessions(transcript_path, sid):
        raw = _topic_read(parent) if topics is None else topics.get(parent, "")
        topic = safe_slug(raw if isinstance(raw, str) else "")
        if not topic:
            continue
        if not session_topic_set(sid, topic):
            return ""
        for suffix in _INHERITED_STATE:
            src = os.path.join(sessions_dir(), parent + suffix)
            dst = os.path.join(sessions_dir(), sid + suffix)
            try:
                if os.path.exists(dst) or not os.path.isfile(src):
                    continue
                if forked_at is not None and os.path.getmtime(src) > forked_at + _FORK_SLACK_S:
                    continue                # recorded by the parent after the fork
                with open(src, "rb") as f:
                    atomic_write_bytes(dst, f.read())
            except OSError:
                pass
        return topic
    return ""


def fork_note_file(sid):
    return os.path.join(sessions_dir(), sid + ".transcript")


def fork_pending(sid):
    return bool(sid) and os.path.exists(fork_note_file(sid))


def _topics_snapshot():
    """{session: topic} for every bound session, right now. Forks that are still
    waiting are resolved first so that a fork of a fork finds its parent bound."""
    try:
        for fn in sorted(n for n in os.listdir(sessions_dir()) if n.endswith(".transcript"))[:50]:
            _inherit_pending(fn[:-len(".transcript")])
        names = sorted(os.listdir(sessions_dir()))      # listed again: resolving creates bindings
    except OSError:
        return {}
    def age(fn):
        try:
            return -os.path.getmtime(os.path.join(sessions_dir(), fn))
        except OSError:
            return 0.0
    out = {}
    for fn in sorted((n for n in names if n.endswith(".topic")), key=age):   # newest first
        if len(out) >= _SNAPSHOT_MAX:
            break
        topic = safe_slug(_topic_read(fn[:-len(".topic")]))
        if topic:
            out[fn[:-len(".topic")]] = topic
    return out


def note_fork(sid, transcript_path, source):
    """SessionStart entry point for a session whose conversation was restored.
    Records a fork so its parent can be resolved once the transcript exists.

    A fork is recognized by `source: fork`, or by a transcript that is not on disk
    yet (a session that has run before always has one). A plain resume matches
    neither, leaves no note, and inherits nothing — see the section comment."""
    if not sid or session_is_degraded(sid) or not transcript_path or safe_slug(_topic_read(sid)):
        return
    if source != "fork" and os.path.exists(transcript_path):
        return
    if fork_pending(sid):
        return                              # keep the original moment and snapshot
    ensure_state()
    atomic_write(fork_note_file(sid), json.dumps(
        {"forked_at": int(time.time()), "transcript": transcript_path, "topics": _topics_snapshot()}))


def _fork_note_read(sid):
    """(forked_at, transcript_path, topics), or (0.0, "", {}) when there is no
    usable note."""
    try:
        with open(fork_note_file(sid), encoding="utf-8") as f:
            note = json.load(f)
        topics = note.get("topics")
        return (float(note["forked_at"]), str(note["transcript"]),
                topics if isinstance(topics, dict) else {})
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return 0.0, "", {}


def _inherit_pending(sid):
    """Resolve a noted fork on first use. The note is dropped once the question is
    settled: a topic was inherited, or Claude Code has had ample time to write the
    transcript head and it names no parent we can use. Until then it is kept, so a
    lookup that lands while the file is still being written does not give up."""
    forked_at, transcript_path, topics = _fork_note_read(sid)
    if not transcript_path:
        return ""
    topic = inherit_from_parent(sid, transcript_path, topics, forked_at)
    settled = bool(topic)
    if not settled and time.time() - forked_at > _FORK_SETTLE_S:
        try:
            settled = os.path.getsize(transcript_path) > 0
        except OSError:
            settled = False                 # never written: the age sweep reclaims the note
    if settled:
        _unlink(fork_note_file(sid))
    return topic


def deps_file(sid):
    return os.path.join(sessions_dir(), sid + ".deps")


def deps_add(sid, dep):
    ensure_state()
    try:
        with open(deps_file(sid), "a") as f:
            f.write(dep + "\n")
    except OSError:
        pass


def deps_read(sid):
    try:
        with open(deps_file(sid)) as f:
            return sorted(set(ln for ln in f.read().split("\n") if ln))
    except OSError:
        return []


def deps_clear(sid):
    _unlink(deps_file(sid))


def pending_clear_file(sid):
    return os.path.join(sessions_dir(), sid + ".pending-clear")


def pending_clear_set(sid, topic, csid, cts):
    ensure_state()
    atomic_write(pending_clear_file(sid), "%s\t%s\t%s" % (topic, csid, cts))


def pending_clear_topic(sid):
    try:
        with open(pending_clear_file(sid)) as f:
            return f.read().split("\t")[0]
    except OSError:
        return ""


def pending_clear_clear(sid):
    _unlink(pending_clear_file(sid))


def compact_file(sid):
    return os.path.join(sessions_dir(), sid + ".compact")


def compact_set(sid, trigger, ts):
    ensure_state()
    atomic_write(compact_file(sid), "trigger=%s\nts=%s\n" % (trigger, ts))


def compact_trigger(sid):
    return kv_get(compact_file(sid), "trigger")


def compact_clear(sid):
    _unlink(compact_file(sid))


def _unlink(path):
    try:
        os.remove(path)
    except OSError:
        pass


# --- cwd hash, pointer, and clears log --------------------------------------

def cwd_hash():
    p = project_dir()
    return hashlib.sha1(p.encode("utf-8", "surrogateescape")).hexdigest()[:16]


def clears_file():
    return os.path.join(cwd_dir(), cwd_hash() + ".clears")


def cwd_lock():
    return os.path.join(cwd_dir(), cwd_hash() + ".lock")


# The per-directory "<cwd-hash>.ptr" pointer that v2 wrote here is gone as of
# 3.3.0: nothing ever read it back, so every save/resume paid a lock and three
# rewrites for state no resolution path consulted. Topic resolution is keyed on
# the session and the clear-baton. Leftover .ptr files are reclaimed by the sweep.


def _clears_append(csid, ctopic):
    ensure_state()
    try:
        with open(clears_file(), "a") as f:
            f.write("%s\t%s\t%s\t-\n" % (now_ms(), csid, ctopic or ""))
    except OSError:
        pass


def clears_append(csid, ctopic):
    with_lock(cwd_lock(), _clears_append, csid, ctopic)


def _clears_claim(nsid, fresh=120):
    """Claim a clear-baton for a new (post-/clear) session. Returns the full
    baton row "<topic>\\t<csid>\\t<cts>" on success, "AMBIGUOUS" if >=2 fresh
    unclaimed, or "" if none / the consume-once rewrite fails."""
    f = clears_file()
    if not os.path.isfile(f):
        return ""
    now = now_ms()
    cutoff = now - fresh * 1000
    try:
        with open(f) as fh:
            rows = fh.read().split("\n")
    except OSError:
        return ""
    # Trailing empty element from a final newline is not a record.
    if rows and rows[-1] == "":
        rows = rows[:-1]
    fresh_idx = []
    for i, line in enumerate(rows):
        parts = line.split("\t")
        if len(parts) >= 4 and parts[3] == "-":
            try:
                ts = int(parts[0])
            except ValueError:
                ts = 0
            if ts >= cutoff:
                fresh_idx.append(i)
    if not fresh_idx:
        return ""
    if len(fresh_idx) > 1:
        return "AMBIGUOUS"
    idx = fresh_idx[0]
    parts = rows[idx].split("\t")
    cts, csid, topic = parts[0], parts[1], parts[2]
    parts[3] = nsid
    rows[idx] = "\t".join(parts)
    # Consume-once: report success ONLY if the rewrite lands; else the baton
    # must remain unclaimed for another session to take.
    d = os.path.dirname(f) or "."
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".clr.", dir=d)
        with os.fdopen(fd, "w") as out:
            out.write("\n".join(rows) + "\n")
        os.replace(tmp, f)
    except OSError:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return ""
    return "%s\t%s\t%s" % (topic, csid, cts)


def clears_claim(nsid, fresh=120):
    return with_lock(cwd_lock(), _clears_claim, nsid, fresh)


# --- Handoff filename / id conventions --------------------------------------
#   manual : <ts>-<sid>.md
#   auto   : <ts>-<sid>-auto.md

_AUTO_RE = re.compile(r"^" + TS_RE + r"-[A-Za-z0-9]+-auto\.md$")
_MANUAL_RE = re.compile(r"^" + TS_RE + r"(-[A-Za-z0-9]+)?\.md$")
# The "<ts>-<sid>" half of an id. Like a slug, this is a single path component
# with no separator, no leading dot, and no glob metacharacter. Matched with
# fullmatch() for the same trailing-newline reason as _SLUG_RE.
_STEM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


# What discovery will consider at all. A handoff's filename is printed in headers
# the model treats as authoritative, and git will happily commit a name containing
# newlines, so anything that is not a plain "<timestamp>….md" name is ignored
# outright. (The tail is left open for names migrated from v1.)
_HANDOFF_NAME_RE = re.compile(TS_RE + r"[A-Za-z0-9._-]{0,120}\.md")


def is_handoff_name(name):
    return bool(_HANDOFF_NAME_RE.fullmatch(name or ""))


def is_auto(name):
    return bool(_AUTO_RE.match(name or ""))


def is_manual(name):
    name = name or ""
    return bool(_MANUAL_RE.match(name)) and not is_auto(name)


def new_handoff_path(mode, sid, slug):
    suffix = "-auto" if mode == "auto" else ""
    return os.path.join(topic_dir(slug), "%s-%s%s.md" % (timestamp(), sid, suffix))


# Any key at column 0 up to the first colon, matching what the old per-key
# scanner accepted (it built `^<literal-key>:` for whatever key it was asked
# for). Narrowing this to identifiers would silently drop hyphenated or
# digit-leading keys that existing handoffs may carry. Leading whitespace is
# excluded so YAML list items ("  - x") are not mistaken for keys.
_FM_LINE = re.compile(r"^([^\s:][^:]*):[ \t]*(.*)$")


def fm_all(path):
    """Parse the leading frontmatter block into a dict in ONE pass, reading only
    as far as the closing fence. Deliberately dumb: scalar `key: value` lines,
    surrounding double quotes stripped, no YAML semantics. First occurrence of a
    key wins (matching the old single-key scan). Callers that need several fields
    should use this instead of repeated fm_get() calls, which reopen the file."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            if f.readline().rstrip("\n") != "---":
                return out
            for ln in f:
                ln = ln.rstrip("\n")
                if ln == "---":
                    break
                m = _FM_LINE.match(ln)
                if not m:
                    continue                    # list items, blanks, junk
                key, val = m.group(1), m.group(2)
                if val.startswith('"'):
                    val = val[1:]
                if val.endswith('"'):
                    val = val[:-1]
                out.setdefault(key, val)
    except OSError:
        return {}
    return out


def fm_get(path, key):
    """Read one scalar frontmatter field (strips surrounding double quotes)."""
    return fm_all(path).get(key, "")


def fm_topic(path, fm=None):
    """The VALIDATED topic of a handoff. Frontmatter is the source of truth, but
    it is also untrusted input from a committed file, so a malformed value falls
    back to the containing directory name and then to "". Never hand a raw
    fm_get(path, "topic") to anything that builds a path or persists state."""
    fm = fm_all(path) if fm is None else fm
    return safe_slug(fm.get("topic", ""), os.path.basename(os.path.dirname(path)))


def fm_quote(s):
    """Quote a scalar for our dumb frontmatter reader (fm_get strips only the
    surrounding double-quotes). Embedded double-quotes are downgraded to single
    quotes so a generated title can never break the frontmatter block, and the
    value is flattened to one line so a title carried forward from an earlier
    handoff cannot smuggle extra frontmatter keys into the new one."""
    return '"%s"' % sanitize_line(s).replace('"', "'")


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_line(s, limit=160):
    """Flatten a single line of untrusted text (a title or task summary read out
    of a committed handoff) before it is injected into model context: collapse it
    to one line, drop control characters, and bound the length. Stops a crafted
    handoff from smuggling extra lines or terminal escapes into a hook's output."""
    s = _CTRL_RE.sub("", (s or "").replace("\r", " ").replace("\n", " "))
    return re.sub(r"[ \t]+", " ", s).strip()[:limit]


def fence(content, label="HANDOFF"):
    """Return (begin, end) delimiters guaranteed to be ABSENT from `content`.

    A fixed marker is forgeable: a committed handoff that itself contains the end
    marker would make everything after it appear to fall outside the data
    boundary — precisely the confusion the boundary exists to prevent. Suffixing
    the label until neither marker occurs in the body makes the fence unspoofable.
    Terminates because a finite string contains finitely many substrings."""
    tag, n = label, 1
    while ("BEGIN " + tag) in content or ("END " + tag) in content:
        n += 1
        tag = "%s-%d" % (label, n)
    return "----- BEGIN %s -----" % tag, "----- END %s -----" % tag


def handoff_id(path):
    """Canonical id: "<topic>/<ts>-<sid>" (sid-qualified)."""
    base = os.path.basename(path)
    stem = base[:-3] if base.endswith(".md") else base
    if stem.endswith("-auto"):
        stem = stem[:-5]
    return "%s/%s" % (fm_topic(path), stem)


def all_handoffs_bytime():
    """All handoff files, oldest->newest by timestamp prefix (across topics).
    Symlinks whose target leaves the handoff tree are dropped — os.walk does not
    follow linked *directories*, but it does yield linked files."""
    d = handoff_dir()
    if not os.path.isdir(d):
        return []
    files = []
    for dirpath, _dirs, filenames in os.walk(d):
        for fn in filenames:
            if not is_handoff_name(fn):
                continue
            p = os.path.join(dirpath, fn)
            if not _within_handoffs(p):
                continue
            files.append((fn, p))
    files.sort(key=lambda t: (t[0], t[1]))
    return [p for _b, p in files]


def latest_auto_for_session(sid):
    result = ""
    for f in all_handoffs_bytime():
        if is_auto(os.path.basename(f)) and fm_get(f, "session_id") == sid:
            result = f
    return result


def is_pending(path):
    """True for an auto-snapshot still awaiting its compaction summary: PreCompact
    wrote the skeleton but PostCompact hasn't filled it (or compaction aborted).
    Pending files are hidden from discovery surfaces (list/resume/recent_topics)."""
    return fm_get(path, "status") == "pending"


def latest_ready_in_topic(slug):
    """Latest non-pending handoff of ANY kind in a topic, or ''. Completed
    auto-snapshots count, so a topic that only ever auto-compacted is resumable.
    `slug` may be untrusted, and a candidate may be a symlink pointing out of the
    tree, so both are checked before the path is returned to a caller that reads it."""
    if not valid_slug(slug):
        return ""
    d = topic_dir(slug)
    if not os.path.isdir(d):
        return ""
    for fn in sorted((fn for fn in os.listdir(d) if is_handoff_name(fn)), reverse=True):
        p = os.path.join(d, fn)
        if not _within_handoffs(p):
            continue
        if not is_pending(p):
            return p
    return ""


def latest_manual_in_topic(slug):
    """Latest hand-written (non-auto) handoff in a topic, or ''. Resume loads the
    newest file of any kind, so after a compaction this is how the handoff a
    session wrote by hand — with its dead ends and constraints — stays reachable."""
    if not valid_slug(slug):
        return ""
    d = topic_dir(slug)
    if not os.path.isdir(d):
        return ""
    for fn in sorted((fn for fn in os.listdir(d) if is_handoff_name(fn)), reverse=True):
        p = os.path.join(d, fn)
        if is_auto(fn) or not _within_handoffs(p) or is_pending(p):
            continue
        return p
    return ""


def recent_topics(limit=5):
    """Up to `limit` most recent topics, newest first: (base, topic, path).
    One row per topic, representative = its newest ready handoff (any kind).
    Reads each file's frontmatter ONCE (status + topic come from the same parse)."""
    d = handoff_dir()
    if not os.path.isdir(d):
        return []
    rows = []
    for dirpath, _dirs, filenames in os.walk(d):
        for fn in filenames:
            if not is_handoff_name(fn):
                continue
            p = os.path.join(dirpath, fn)
            if not _within_handoffs(p):          # symlink out of the tree
                continue
            fm = fm_all(p)
            if fm.get("status") == "pending":    # skip un-filled auto skeletons
                continue
            topic = fm_topic(p, fm)
            if not topic:                        # unusable/malformed topic
                continue
            rows.append((fn, topic, p))
    rows.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    seen = set()
    out = []
    for base, topic, path in rows:
        if topic in seen:
            continue
        seen.add(topic)
        out.append((base, topic, path))
        if len(out) >= limit:
            break
    return out


def _within_handoffs(path):
    """True if `path` resolves to a location inside the handoff directory."""
    try:
        base = os.path.realpath(handoff_dir())
        rp = os.path.realpath(path)
    except OSError:
        return False
    return rp == base or rp.startswith(base + os.sep)


def resolve_id(q):
    """Resolve a "<topic>/<stem>" id or a bare topic slug to a handoff path.
    A bare "<topic>/<timestamp>" alias resolves only when UNAMBIGUOUS. Ids are
    untrusted input, so reject anything that could escape the handoff tree."""
    q = q or ""
    d = handoff_dir()
    if "/" in q:
        topic, stem = q.split("/", 1)
        # Both halves must be single, well-formed path components. The grammars
        # exclude "/" , a leading dot, and every glob metacharacter, so the
        # prefix search below cannot be steered outside the topic directory;
        # glob.escape() keeps that true even if the grammar is ever widened.
        if not valid_slug(topic) or not _STEM_RE.fullmatch(stem):
            return ""
        for cand in (os.path.join(d, topic, stem + ".md"),
                     os.path.join(d, topic, stem + "-auto.md")):
            if (is_handoff_name(os.path.basename(cand)) and os.path.isfile(cand)
                    and _within_handoffs(cand) and not is_pending(cand)):
                return cand
        pattern = os.path.join(d, glob.escape(topic), glob.escape(stem) + "*.md")
        matches = sorted(g for g in glob.glob(pattern)
                         if is_handoff_name(os.path.basename(g))
                         and _within_handoffs(g) and not is_pending(g))
        return matches[0] if len(matches) == 1 else ""
    if not valid_slug(q):
        return ""
    f = latest_ready_in_topic(q)
    return f if (f and _within_handoffs(f)) else ""


def handoff_when(base):
    """Reformat a basename's timestamp prefix to "YYYY-MM-DD HH:MM"."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})\d{2}", base or "")
    return "%s %s:%s" % (m.group(1), m.group(2), m.group(3)) if m else ""


def _primary_request_line(lines):
    """Fallback summary source for auto-snapshots whose body is a Claude Code
    compaction summary: it carries '1. Primary Request and Intent:' instead of a
    '## Task & progress' section."""
    for i, ln in enumerate(lines):
        m = re.search(r"Primary Request and Intent[ \t]*:?[ \t]*(.*)", ln)
        if not m:
            continue
        tail = re.sub(r"^\*+[ \t]*", "", m.group(1).strip())
        if tail:
            return tail
        for nxt in lines[i + 1:]:                # header-only line: use the next real line
            if re.match(r"^[ \t]*$", nxt) or re.match(r"^[ \t]*<!--", nxt):
                continue
            if re.match(r"^[ \t]*(#|[0-9]+\.[ \t])", nxt):   # next section/heading: no inline summary
                return ""
            return nxt
        return ""
    return ""


def handoff_summary(path):
    """One-line task summary from a handoff's "## Task & progress" section, or
    (for auto-snapshots) from the compaction summary's "Primary Request and Intent"."""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return ""
    insec = False
    raw = ""
    for ln in lines:
        if re.match(r"^##[ \t]+Task & progress[ \t]*$", ln):
            insec = True
            continue
        if insec and re.match(r"^##[ \t]", ln):
            break
        if insec:
            if re.match(r"^[ \t]*$", ln):
                continue
            if re.match(r"^[ \t]*<!--", ln):
                continue
            if re.match(r"^[ \t]*#", ln):
                continue
            raw = ln
            break
    if not raw:
        raw = _primary_request_line(lines)
    s = re.sub(r"^[ \t]*([-*+]|[0-9]+\.)[ \t]+", "", raw)
    s = re.sub(r"^[ \t]*\[[ xX]\][ \t]*", "", s)
    s = s.replace("**", "")
    s = s.strip()
    return s[:100]


# --- Slug derivation --------------------------------------------------------

def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+", "", s)
    s = re.sub(r"-+$", "", s)
    s = s[:40]
    s = re.sub(r"-+$", "", s)
    return s


def unique_topic_slug(text):
    """Derive an unused topic slug and RESERVE it by creating the directory.

    Reservation is the point: the old isdir()-then-use check let two topicless
    sessions starting in the same second both settle on "topic-<ts>" and silently
    merge two unrelated workstreams into one topic. os.mkdir is atomic, so exactly
    one racer can win a given name and the loser moves on to the next suffix."""
    base = slugify(text)
    if not valid_slug(base):
        base = "topic-" + timestamp()
    for n in range(1, 1000):
        slug = base if n == 1 else "%s-%d" % (base, n)
        try:
            os.makedirs(topic_dir(slug))
            return slug
        except FileExistsError:
            continue
        except OSError:
            return slug          # can't create (read-only fs): caller degrades
    # 999 collisions on one base: fall back to a name that cannot already be
    # taken, and still return only after attempting to reserve it — never hand
    # back a name this function has not tried to claim.
    slug = "%s-%d" % (base, os.getpid())
    try:
        os.makedirs(topic_dir(slug), exist_ok=True)
    except OSError:
        pass
    return slug


# --- Deterministic project facts --------------------------------------------

def git(*args):
    try:
        left = _git_left()
        if left <= 0:
            return ""
        r = subprocess.run(["git", "-C", project_dir(), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=min(left, 20))
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def in_git():
    try:
        r = subprocess.run(["git", "-C", project_dir(), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=max(0.1, min(_git_left(), 20)))
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def detect_commands():
    d = project_dir()
    out = []
    found = False

    pj = os.path.join(d, "package.json")
    if os.path.isfile(pj):
        out.append("- Node project (`package.json`). Scripts:")
        try:
            with open(pj) as f:
                data = json.load(f)
            for k in (data.get("scripts") or {}):
                out.append("    - `npm run %s`" % k)
        except (OSError, ValueError):
            pass
        found = True

    mk = os.path.join(d, "Makefile")
    if os.path.isfile(mk):
        out.append("- Makefile targets:")
        try:
            with open(mk) as f:
                targets = [m.group(1) for m in
                           (re.match(r"^([a-zA-Z0-9_.-]+):", ln) for ln in f.read().split("\n"))
                           if m]
            for t in targets[:20]:
                out.append("    - make %s" % t)
        except OSError:
            pass
        found = True

    simple = [
        ("pyproject.toml", "- Python project (`pyproject.toml`)."),
        ("requirements.txt", "- Python deps: `pip install -r requirements.txt`"),
        ("Cargo.toml", "- Rust: `cargo build`, `cargo test`."),
        ("go.mod", "- Go module: `go build ./...`, `go test ./...`."),
        ("Gemfile", "- Ruby: `bundle install`."),
        ("pom.xml", "- Maven: `mvn install`, `mvn test`."),
    ]
    for fname, line in simple:
        if os.path.isfile(os.path.join(d, fname)):
            out.append(line)
            found = True

    if os.path.isfile(os.path.join(d, "build.gradle")) or os.path.isfile(os.path.join(d, "build.gradle.kts")):
        out.append("- Gradle: `./gradlew build`, `./gradlew test`.")
        found = True
    if os.path.isfile(os.path.join(d, "docker-compose.yml")) or os.path.isfile(os.path.join(d, "compose.yaml")):
        out.append("- Docker Compose present: `docker compose up`.")
        found = True

    if not found:
        out.append("- _No common build files detected — fill in manually._")
    return "\n".join(out)


def facts():
    out = ["## Repo snapshot", ""]
    if in_git():
        branch = git("rev-parse", "--abbrev-ref", "HEAD").strip() or "unknown"
        out.append("- Branch: `%s`" % branch)
        out.append("- Working tree:")
        out.append("```")
        st = git("status", "--short").rstrip("\n")
        if st:
            out.append(st)
        out.append("```")
        out.append("- Recent commits:")
        out.append("```")
        lg = git("log", "--oneline", "-5").rstrip("\n")
        if lg:
            out.append(lg)
        out.append("```")
        if _git_left() <= 0:
            out.append("- _git did not answer within the time limit, so this snapshot may be "
                       "incomplete. Run `git status` and `git log` to see the real state._")
    else:
        out.append("- _Not a git repository._")
    out.append("")
    out.append("## Environment, commands & results")
    out.append("")
    out.append(detect_commands())
    return "\n".join(out)


# --- Recorded repo state, age, and drift ------------------------------------
#
# A handoff is a set of claims made at one moment. new-path.py and the compaction
# hooks record where the repo stood at that moment (frontmatter `head`, `branch`,
# `tree_state`), and resume.py compares it with the present, so "is this still
# true?" is answered by a script instead of being left to the model's judgment.
#
# The comparison is about FILE CONTENT, not about commits. `tree_state` digests
# every path whose working-tree content differs from the recorded commit, plus
# every untracked file. On resume the same digest is computed against that SAME
# recorded commit, so it comes out equal exactly when every file is as it was —
# even if the saved work has since been committed, or the handoff itself was
# (a file cannot record the hash of the commit that contains it, so comparing
# commit ids would report every committed handoff as drifted).
#
# Not compared, by design: ignored files, and what is staged versus unstaged.

# A full object id only. An abbreviated one could be shadowed by a ref of the same
# name (git resolves refs before short ids); a full id is always read as an id.
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
# Never part of the comparison, wherever in the repository they sit: handoff trees
# (this project's, and those of other projects in the same repository — writing a
# handoff must not read as a change to anyone), and Claude Code's agent worktrees,
# which are separate checkouts that come and go.
# Tracked files that merely live under one of these names are still compared: the
# handoff exclusion is limited to the plugin's own subdirectories, and the worktree
# exclusion applies to untracked entries only.
_HANDOFF_EXCLUDES = (":(exclude,glob)**/.claude/sekekama/session-handoff/handoffs/**",
                     ":(exclude,glob)**/.claude/sekekama/session-handoff/.state/**")
_UNTRACKED_EXCLUDES = _HANDOFF_EXCLUDES + (":(exclude,glob)**/.claude/worktrees/**",)
_HASH_BUDGET = 32 * 1024 * 1024       # bytes of changed-file content read per digest
_WALK_FILES = 20000                   # files read inside untracked nested directories
_NEST_DEPTH = 3                       # how far to follow submodules inside submodules
_GIT_BUDGET_S = 20.0                  # total seconds one process may wait on git
_GIT_DEADLINE = [None]
# File names are repository content on their way into a script-authored header.
# Only plain ones are shown; the rest are counted.
_NAME_SHOW_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/@+-]{0,199}")
# Branch names are echoed into a script-authored header, and the recorded one
# comes from a committed file. Only a conservative, punctuation-poor name is shown.
_REF_SHOW_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@+-]{0,199}")


def _git_left():
    """Seconds this process may still spend waiting on git. One budget for the
    whole process, so a slow or hung git cannot stall a hook for a multiple of
    the per-call timeout."""
    if _GIT_DEADLINE[0] is None:
        _GIT_DEADLINE[0] = time.monotonic() + _GIT_BUDGET_S
    return _GIT_DEADLINE[0] - time.monotonic()


def _git_run(*args, cwd=None):
    """Run git (in the project dir unless `cwd` is given). Returns (returncode,
    stdout bytes), or (-1, b"") when git could not be run, did not finish in time,
    or the process has used up its git budget. Bytes, not text: paths, branch
    names and commit subjects need not be UTF-8."""
    left = _git_left()
    if left <= 0:
        return -1, b""
    try:
        r = subprocess.run(["git", "-C", cwd or project_dir(), *args],
                           capture_output=True, timeout=min(left, 20))
    except (OSError, subprocess.SubprocessError):
        return -1, b""
    return r.returncode, r.stdout


def _git_text(*args):
    rc, out = _git_run(*args)
    return out.decode("utf-8", "replace") if rc == 0 else ""


def _norm_branch(name):
    """A branch name as it survives a round trip through our frontmatter reader."""
    return sanitize_line(name).strip('"')


def _show_ref(name):
    """A branch name fit to print in the header, or a placeholder."""
    return "`%s`" % name if _REF_SHOW_RE.fullmatch(name or "") else "(name not shown)"


def _toplevel(cwd=None):
    rc, top = _git_run("rev-parse", "--show-toplevel", cwd=cwd)
    return os.fsdecode(top.rstrip(b"\r\n")) if rc == 0 and top.strip() else ""


def _changed_paths(base, top):
    """(tracked, untracked): repo-relative byte paths whose working-tree content
    differs from commit `base`, and untracked files. None when undeterminable.

    Both commands run AT THE TOP of the repository with `.` as the pathspec, so
    they cover all of it and report paths relative to the same directory. (Run
    from a subdirectory, `ls-files --others` reports relative to that directory
    while `diff` reports relative to the top.)"""
    rc, diff = _git_run("diff", "--name-only", "-z", "--no-renames", "--ignore-submodules=none",
                        base, "--", ".", *_HANDOFF_EXCLUDES, cwd=top)
    if rc != 0:
        return None
    rc, others = _git_run("ls-files", "--others", "--exclude-standard", "--full-name", "-z",
                          "--", ".", *_UNTRACKED_EXCLUDES, cwd=top)
    if rc != 0:
        return None
    return (sorted(set(t for t in diff.split(b"\0") if t)),
            sorted(set(t for t in others.split(b"\0") if t)))


def _file_digest(p, budget):
    """One non-directory path (bytes): what kind of thing it is, and its content."""
    try:
        info = os.lstat(p)
    except OSError:
        return b"gone"
    if stat.S_ISLNK(info.st_mode):
        try:
            return b"link:" + os.fsencode(os.readlink(p))
        except OSError:
            return b"link?"
    if not stat.S_ISREG(info.st_mode):
        return b"special"
    if info.st_size > budget[0]:            # too much to read: fall back to size + mtime
        return ("big:%d:%d" % (info.st_size, info.st_mtime_ns)).encode()
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError:
        return b"unreadable"
    budget[0] -= len(data)
    return b"file:%d:" % (1 if info.st_mode & 0o111 else 0) + hashlib.sha1(data).digest()


def _walk_digest(root, budget):
    """A directory git reports as a single untracked entry — in practice a nested
    repository that is not a submodule. Its files are read directly: git is NOT
    run inside it, because doing so would execute whatever that repository's own
    config says (an fsmonitor hook, a filter), and nothing vouches for a nested
    repository the way the user's own `git status` vouches for a submodule.
    Returns None when the tree is too large to read within the file budget."""
    h = hashlib.sha1()
    for dirpath, dirs, files in os.walk(root):
        keep = []
        for d in sorted(dirs):
            full = os.path.join(dirpath, d)
            if os.path.islink(full):
                h.update(b"\0" + os.path.relpath(full, root) + b"\0" + _file_digest(full, budget))
            elif d != b".git":
                keep.append(d)
        dirs[:] = keep
        for fn in sorted(files):
            if fn == b".git":
                continue
            budget[1] -= 1
            if budget[1] < 0:
                return None
            full = os.path.join(dirpath, fn)
            h.update(b"\0" + os.path.relpath(full, root) + b"\0" + _file_digest(full, budget))
    return h.digest()


def _is_gitlink(top, relp):
    """True when the index records `relp` as a submodule (mode 160000). A directory
    that merely appears in the diff — a tracked file replaced by a directory, say —
    is not one, and git must not be run inside it."""
    rc, out = _git_run("ls-files", "--stage", "-z", "--", ":(literal)" + os.fsdecode(relp), cwd=top)
    return rc == 0 and out.startswith(b"160000 ")


def _submodule_digest(p, depth, budget):
    """A tracked submodule: its checked-out commit plus the digest of its own
    changes. git already runs inside a submodule whenever the user runs `git
    status` in the superproject, so doing the same here is no new exposure."""
    sub = os.fsdecode(p)
    rc, head = _git_run("rev-parse", "--verify", "--quiet", "HEAD^{commit}", cwd=sub)
    head = head.strip() if rc == 0 else b""
    if not head or _toplevel(sub) != os.path.realpath(sub):
        return _walk_digest(p, budget)      # not initialized: just a directory
    if depth <= 0:
        return None
    inner = _content_digest(head.decode("ascii", "replace"), depth - 1, budget, sub)
    return None if inner is None else head + b":" + inner


def _content_digest(base, depth, budget, top, found=None):
    """Digest of how the working tree of the repository at `top` differs from
    commit `base`: b"" when it does not, None when it cannot be determined.
    `budget` is [bytes left to read, files left to walk], shared across nesting.
    `found` is a _changed_paths() result the caller already has."""
    if found is None:
        found = _changed_paths(base, top)
    if found is None:
        return None
    tracked, untracked = found
    paths = sorted(set(tracked) | set(untracked))
    if not paths:
        return b""
    top_b, loose = os.fsencode(top), set(untracked)
    h = hashlib.sha1()
    for relp in paths:
        p = os.path.join(top_b, relp)
        if os.path.isdir(p) and not os.path.islink(p):
            part = (_submodule_digest(p, depth, budget) if relp not in loose and _is_gitlink(top, relp)
                    else _walk_digest(p, budget))
            if part is None:
                return None
            part = b"dir:" + part
        else:
            part = _file_digest(p, budget)
        h.update(b"\0" + relp + b"\0" + part)
    return h.digest()


def tree_state(base="HEAD"):
    """How the working tree differs from commit `base`: "clean", "dirty-<16 hex>",
    or "" when it cannot be determined. See the section comment for why the base
    is a parameter: resume passes the commit the handoff recorded."""
    return tree_state_names(base)[0]


def tree_state_names(base="HEAD"):
    """(tree_state, names of the paths that differ from `base`), from one pass."""
    top = _toplevel()
    found = _changed_paths(base, top) if top else None
    if found is None:
        return "", []
    d = _content_digest(base, _NEST_DEPTH, [_HASH_BUDGET, _WALK_FILES], top, found)
    if d is None:
        return "", []
    names = sorted(t.decode("utf-8", "replace") for t in set(found[0]) | set(found[1]))
    return ("dirty-" + d.hex()[:16] if d else "clean"), names


def _head():
    rc, out = _git_run("rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    head = out.decode("ascii", "replace").strip() if rc == 0 else ""
    return head if _SHA_RE.fullmatch(head) else ""


def git_state():
    """(head, branch, tree_state) of the project right now, or ("", "", "") when
    it is not a git repository or has no commit yet."""
    head = _head()
    if not head:
        return "", "", ""
    return head, _norm_branch(_git_text("rev-parse", "--abbrev-ref", "HEAD").strip()), tree_state(head)


def git_fm_lines():
    """Frontmatter lines recording the repo state a handoff was written against."""
    head, branch, tree = git_state()
    if not head:
        return []
    out = ["head: " + head]
    if branch:
        out.append("branch: " + branch)
    if tree:
        out.append("tree_state: " + tree)
    return out


def _rev_count(a, b):
    rc, out = _git_run("rev-list", "--count", "%s..%s" % (a, b))
    try:
        return int(out.strip()) if rc == 0 else 0
    except ValueError:
        return 0


def _head_moved(saved, head):
    """Lines describing how HEAD relates to the recorded commit (which exists)."""
    s, h = saved[:10], head[:10]
    if _git_run("merge-base", "--is-ancestor", saved, head)[0] == 0:
        n = _rev_count(saved, head)
        out = ["- HEAD: %d commit(s) since the handoff (%s..%s):" % (n, s, h)]
        # Commit subjects are repo content on their way into model context. The -c
        # and --no-decorate keep user config from adding lines of its own.
        log = _git_text("-c", "log.showSignature=false", "log", "--oneline", "--no-decorate",
                        "-10", "%s..%s" % (saved, head))
        for ln in log.splitlines():
            out.append("    " + sanitize_line(ln, 120))
        if n > 10:
            out.append("    ... and %d more" % (n - 10))
        return out
    if _git_run("merge-base", "--is-ancestor", head, saved)[0] == 0:
        return ["- HEAD: now at %s, %d commit(s) BEHIND the recorded commit %s (a reset, or a "
                "different branch)." % (h, _rev_count(head, saved), s)]
    return ["- HEAD: now at %s. History has diverged from the recorded commit %s (a rebase, a "
            "reset, or a different branch)." % (h, s)]


_FILES_HEADING = re.compile(r"^##[ \t]+Files & code touched[ \t]*$")
_BULLET_PATH = re.compile(r"^[ \t]*[-*+][ \t]+`([^`]+)`")
_NOT_A_PATH = set(" \t*?<>()[]{}|$\\\"'")


def listed_files(path):
    """Project files named under "## Files & code touched", as (shown, absolute)
    pairs. Only the leading `backticked` token of each bullet is read, and only
    when it looks like a project-relative file path — a function name or a glob is
    skipped. The handoff is untrusted, so a path that leaves the project directory
    is dropped here and never probed."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return []
    base = os.path.normpath(project_dir())
    out, seen, insec = [], set(), False
    for ln in lines:
        if _FILES_HEADING.match(ln):
            insec = True
            continue
        if insec and re.match(r"^##[ \t]", ln):
            break
        m = _BULLET_PATH.match(ln) if insec else None
        if not m:
            continue
        cand = m.group(1).strip()
        cand = re.sub(r"(::.*|#L[0-9].*|:[0-9]+(-[0-9]+)?)$", "", cand)
        if (not cand or cand in seen or cand[0] in "-~" or "://" in cand
                or _NOT_A_PATH & set(cand) or _CTRL_RE.search(cand)):
            continue
        if "/" not in cand and not re.search(r"\.[A-Za-z0-9]{1,8}$", cand):
            continue                        # a bare word: more likely a symbol than a file
        seen.add(cand)
        p = os.path.normpath(os.path.join(base, cand))
        if p != base and not p.startswith(base + os.sep):
            continue
        out.append((cand, p))
    return out


def _names(names, limit=8):
    """Path names for a header line. Only plain names are printed — a file can be
    called anything, including a sentence addressed to the reader — and the rest
    are counted."""
    plain = [n for n in names if _NAME_SHOW_RE.fullmatch(n)]
    shown = ", ".join("`%s`" % n for n in plain[:limit])
    extra = []
    if len(plain) > limit:
        extra.append("%d more" % (len(plain) - limit))
    if len(names) > len(plain):
        extra.append("%d with a name that is not shown" % (len(names) - len(plain)))
    if not extra:
        return shown
    return (shown + " " if shown else "") + "(%s%s)" % ("and " if shown else "", ", ".join(extra))


def missing_files(path, limit=8):
    """Listed files that no longer exist, as (shown, total)."""
    gone = [c for c, p in listed_files(path) if not os.path.lexists(p)]
    return gone[:limit], len(gone)


def _saved_epoch(path, fm):
    """Best estimate of when a handoff was written, as seconds since the epoch: the
    earlier of its `created` field and the file's own mtime. Taking the earlier one
    means a forged or future `created` can only make more files look changed."""
    cands = []
    dt = _created_dt(path, fm)
    if dt is not None:
        try:
            cands.append(dt.timestamp())
        except (OverflowError, OSError, ValueError):
            pass
    try:
        cands.append(os.path.getmtime(path))
    except OSError:
        pass
    return min(cands) if cands else None


def _check_without_git(path, fm):
    """No commit to compare against, so look at the only thing the handoff pins
    down: the files it names. Modification times are meaningful here because
    nothing has been checked out or cloned over them."""
    lines = ["- Not a git repository, so there is no commit or working tree to compare."]
    listed = listed_files(path)
    saved = _saved_epoch(path, fm)
    gone = [c for c, p in listed if not os.path.lexists(p)]
    newer = []
    if saved is not None:
        for c, p in listed:
            try:
                if os.path.getmtime(p) > saved + 2:
                    newer.append(c)
            except OSError:
                pass
    if newer:
        lines.append("- Files: %d file(s) this handoff names were modified after it was saved: %s."
                     % (len(newer), _names(newer)))
    if gone:
        lines.append("- Files: %d path(s) this handoff names do not exist now: %s. Expected if the "
                     "handoff says they were removed or renamed." % (len(gone), _names(gone)))
    if not listed:
        lines.append("- This handoff names no files to check. Look over the project by hand before "
                     "relying on it.")
    elif not newer and not gone:
        lines.append("- Files: the %d file(s) this handoff names exist and have not been modified "
                     "since it was saved. Files it does not name were not checked, so look over the "
                     "project by hand before relying on it." % len(listed))
    else:
        lines.append("- Check by hand that the files this handoff names look as it describes.")
    return ("DRIFT" if newer else "UNVERIFIED"), lines


def state_check(path, fm=None):
    """Compare the state a handoff recorded with the present.

    Returns (verdict, detail_lines):
      CLEAN       same branch, and every file has the content it had at save time
      DRIFT       something moved; the detail lines say what
      UNVERIFIED  nothing reliable to compare against (no git, or a handoff that
                  records no commit) — the caller checks by hand

    Frontmatter comes from a committed file, so it is untrusted: `head` reaches git
    only as a full hexadecimal object id, `tree_state` is compared and never
    echoed, and `branch` is echoed only when it is a plain ref name."""
    fm = fm_all(path) if fm is None else fm
    if not in_git():
        return _check_without_git(path, fm)
    saved_head = fm.get("head", "")
    if not _SHA_RE.fullmatch(saved_head):
        saved_head = ""
    lines, drift, verified = [], False, False
    head = _head()
    if not saved_head:
        lines.append("- This handoff does not record the commit it was written at (an older plugin "
                     "version, or a repository with no commits). Compare its Repo snapshot section "
                     "with `git status`, the current branch and `git log` by hand.")
    elif not head:
        drift = True
        lines.append("- HEAD: the repository has no commit now, but the handoff was saved at %s."
                     % saved_head[:10])
    elif _git_run("cat-file", "-e", saved_head + "^{commit}")[0] != 0:
        drift = True
        lines.append("- HEAD: now at %s. The recorded commit %s is not in this repository (a "
                     "different clone, a shallow clone, or rewritten history), so file contents "
                     "cannot be compared." % (head[:10], saved_head[:10]))
    else:
        verified = True
        saved_branch = _norm_branch(fm.get("branch", ""))
        branch = _norm_branch(_git_text("rev-parse", "--abbrev-ref", "HEAD").strip())
        if saved_branch and branch and saved_branch != branch:
            drift = True
            lines.append("- Branch: saved on %s, now on %s." % (_show_ref(saved_branch), _show_ref(branch)))
        if head != saved_head:
            lines.extend(_head_moved(saved_head, head))
        saved_tree = fm.get("tree_state", "")
        tree, now = tree_state_names(saved_head)    # measured against the RECORDED commit
        if not saved_tree or not tree:
            verified = False
            lines.append("- Files: file contents could not be compared with save time. Check "
                         "`git status` and `git diff` by hand.")
        elif saved_tree != tree:
            drift = True
            if saved_tree == "clean":
                lines.append("- Files: the working tree matched commit %s at save time; %d path(s) "
                             "differ from it now: %s." % (saved_head[:10], len(now), _names(now)))
            elif tree == "clean":
                lines.append("- Files: there was uncommitted work at save time, and the working tree "
                             "now matches commit %s exactly, so that work is gone from the files "
                             "(discarded or stashed)." % saved_head[:10])
            else:
                lines.append("- Files: the content that differs from commit %s is not what it was "
                             "at save time (%d path(s) differ from that commit now)."
                             % (saved_head[:10], len(now)))
        elif head != saved_head:
            lines.append("- Files: every file has the content it had at save time; the commits "
                         "above did not change what is on disk.")
    verdict = "DRIFT" if drift else ("CLEAN" if verified else "UNVERIFIED")
    if verdict != "CLEAN":
        # With unchanged content, a missing path was already missing when the
        # handoff was written, so it is only worth reporting once something moved.
        shown, total = missing_files(path)
        if shown:
            more = " (and %d more)" % (total - len(shown)) if total > len(shown) else ""
            lines.append("- Files: %d path(s) listed under \"Files & code touched\" do not exist now%s: %s. "
                         "Expected if the handoff says they were removed or renamed."
                         % (total, more, _names(shown)))
    return verdict, lines


def _ago(seconds):
    if seconds < -300:
        return "dated in the future, so its age is unknown"
    if seconds < 90:
        return "just now"
    if seconds < 90 * 60:
        return "%d minutes ago" % round(seconds / 60)
    if seconds < 36 * 3600:
        return "%d hours ago" % round(seconds / 3600)
    return "%d days ago" % round(seconds / 86400)


def _created_dt(path, fm):
    """When a handoff says it was written: frontmatter `created`, else the
    filename's timestamp (local time). None when neither parses."""
    dt = None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(fm.get("created", ""), fmt)
            break
        except ValueError:
            pass
    if dt is None:
        m = re.match(TS_RE, os.path.basename(path))
        if m:
            try:
                dt = datetime.strptime(m.group(0), "%Y-%m-%d-%H%M%S")
            except ValueError:
                dt = None
    if dt is None:
        return None
    try:
        return dt.astimezone()              # naive values are taken as local time
    except (OverflowError, OSError, ValueError):
        return None


def handoff_saved(path, fm=None):
    """When a handoff was written, as ("YYYY-MM-DD HH:MM", "N days ago"), or
    ("", "") when unknown. The date is the handoff's own claim; a value in the
    future is reported as such instead of being shown as fresh."""
    fm = fm_all(path) if fm is None else fm
    dt = _created_dt(path, fm)
    if dt is None:
        return "", ""
    try:
        secs = (datetime.now().astimezone() - dt).total_seconds()
        return dt.strftime("%Y-%m-%d %H:%M"), _ago(secs)
    except (OverflowError, OSError, ValueError):
        return "", ""


def show_path(path, absolute=False):
    """A path fit to print in a script-authored header: one bounded line. Handoff
    paths are built from validated slugs and names, so this is a second line of
    defence, not the first."""
    return sanitize_line(path if absolute else rel(path), 600)


# --- Provenance ---------------------------------------------------------------
#
# The state check says whether a handoff is STALE. It says nothing about who wrote
# it: a handoff that arrives through a clone can carry whatever frontmatter earns
# a CLEAN verdict. So the plugin also keeps a receipt, outside the repository, of
# every handoff it wrote on this machine (a hash of the file as written). Only a
# handoff with a matching receipt may be auto-executed; anything else — a
# teammate's, another clone's, or one edited after it was saved — is reviewed with
# the user first.

def _receipts_file():
    return os.path.join(state_dir(), "receipts", cwd_hash() + ".sha256")


def _state_is_private():
    """Receipts mean something only when the state dir is outside the project: the
    in-repo fallback could be populated by whoever authored the branch."""
    return not os.path.normpath(state_dir()).endswith(_INREPO_STATE_SUFFIX)


def _file_sha256(path):
    """Hash of a handoff's content, insensitive to the two byte-level changes
    tooling makes without anyone editing the file: line-ending conversion (git
    autocrlf) and trailing newlines (an end-of-file fixer)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ""
    return hashlib.sha256(data.replace(b"\r\n", b"\n").rstrip(b"\n")).hexdigest()


def receipt_add(path):
    """Record that this machine wrote the handoff at `path`, as it is right now."""
    digest = _file_sha256(path)
    if not digest or not _state_is_private():
        return
    try:
        os.makedirs(os.path.dirname(_receipts_file()), exist_ok=True)
        with open(_receipts_file(), "a") as f:
            f.write(digest + "\n")
    except OSError:
        pass


def saved_here(path):
    """True when this machine wrote this exact handoff content."""
    digest = _file_sha256(path)
    if not digest or not _state_is_private():
        return False
    try:
        with open(_receipts_file()) as f:
            return digest in f.read().split()
    except OSError:
        return False


def rel(path):
    """Strip the project-dir prefix for tidy display paths."""
    base = project_dir() + os.sep
    return path[len(base):] if path.startswith(base) else path


def ignored_notice(path):
    """One-time, per-project notice when saved handoffs land somewhere git ignores.

    V2-SPEC §3.3 keeps the commit posture neutral — the plugin never edits
    .gitignore — but a wholesale-ignored `.claude/` silently turns a feature sold
    as shareable into a local-only one, and git cannot re-include a subtree under
    it. Returns the message once per project, then "" forever after."""
    marker = os.path.join(state_dir(), ".ignore-notice")
    if os.path.exists(marker) or not in_git():
        return ""
    try:
        r = subprocess.run(["git", "-C", project_dir(), "check-ignore", "-q", path],
                           capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.returncode != 0:                      # 1 = not ignored, 128 = error
        return ""
    ensure_state()
    atomic_write(marker, str(now_ms()))
    return ("Note: git ignores %s, so handoffs in this project stay local — they won't be "
            "committed or shared with teammates. That's a valid setup; if you'd rather track "
            "them, ignore `.claude/` granularly (e.g. only `.claude/settings.local.json`) "
            "instead of as a whole, because git cannot re-include a subtree under a fully "
            "ignored directory. Shown once per project." % rel(path))


# --- Age-based GC sweep -----------------------------------------------------

def gc_sweep(ttl_days=14, keep_sid=""):
    """Reclaim stale ephemeral state (incl. crash/kill leaks). Throttled ~1/hr.

    `keep_sid` is the live session's id and is never reclaimed: a session resumed
    from a transcript older than the TTL keeps its own id, so an age-only rule
    would delete the topic binding of the very session doing the sweeping.

    The sweep only ever touches ephemeral state, never committed handoffs
    (V2-SPEC.md "the sweep never touches committed handoffs")."""
    ensure_state()
    sdir, cdir, sweepdir = sessions_dir(), cwd_dir(), state_dir()
    stamp = os.path.join(sweepdir, ".gc.stamp")
    now = now_ms()
    last = 0
    try:
        with open(stamp) as f:
            txt = f.read().strip()
        last = int(txt) if txt.isdigit() else 0
    except (OSError, ValueError):
        last = 0
    if now - last < 3600000:
        return
    try:
        with open(stamp, "w") as f:
            f.write(str(now))
    except OSError:
        pass

    cutoff_mtime = time.time() - ttl_days * 1440 * 60
    if os.path.isdir(sdir):
        for fn in os.listdir(sdir):
            if keep_sid and fn.startswith(keep_sid + "."):
                continue                    # never reclaim the live session
            fp = os.path.join(sdir, fn)
            try:
                if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff_mtime:
                    os.remove(fp)
            except OSError:
                pass
    if os.path.isdir(sweepdir):
        for fn in os.listdir(sweepdir):
            if fn.startswith("enforce.") and fn.endswith(".count"):
                fp = os.path.join(sweepdir, fn)
                try:
                    if os.path.getmtime(fp) < cutoff_mtime:
                        os.remove(fp)
                except OSError:
                    pass

    cutoff_ms = now - ttl_days * 86400 * 1000
    if os.path.isdir(cdir):
        for fn in os.listdir(cdir):
            if fn.endswith(".ptr"):         # pointer files left by <=3.2.0
                fp = os.path.join(cdir, fn)
                try:
                    if os.path.getmtime(fp) < cutoff_mtime:
                        os.remove(fp)
                except OSError:
                    pass
                continue
            if not fn.endswith(".clears"):
                continue
            cf = os.path.join(cdir, fn)
            try:
                with open(cf) as f:
                    rows = f.read().split("\n")
                kept = []
                for ln in rows:
                    if not ln:
                        continue
                    try:
                        ts = int(ln.split("\t")[0])
                    except (ValueError, IndexError):
                        ts = 0
                    if ts >= cutoff_ms:
                        kept.append(ln)
                atomic_write(cf, ("\n".join(kept) + "\n") if kept else "")
            except OSError:
                pass


# --- Legacy handoff migration -----------------------------------------------

_LEGACY_README = """# Migrated to session-handoff v2

These v1 handoffs were copied (not moved) to:

    .claude/sekekama/session-handoff/handoffs/legacy/

with schema-2 frontmatter (topic: legacy). The originals here are kept as a backup
and are no longer read by the plugin. Use /session-handoff:list --any to browse, or
/session-handoff:resume legacy to continue the legacy thread. You may delete this
directory once you've confirmed the migration.
"""


def _ts_to_iso(ts):
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})(\d{2})$", ts or "")
    return "%sT%s:%s:%s" % (m.group(1), m.group(2), m.group(3), m.group(4)) if m else ""


def _normalize_legacy_fm(raw, sid, created, kind, fn):
    """A v1 handoff may already open with a `---` block, but a v1 block lacks the
    schema-2 keys the plugin indexes on. Copying it verbatim produced a migrated
    file with no `topic:`, which discovery then skipped — migrated but invisible.
    Splice in only the keys that are missing, leaving existing values alone."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw                     # non-UTF-8: copy byte-for-byte, never corrupt
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return raw
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:                    # unterminated block: leave it alone
        return raw
    present = set()
    for ln in lines[1:end]:
        m = _FM_LINE.match(ln)
        if m:
            present.add(m.group(1))
    add = []
    for key, val in (("schema", "2"),
                     ("topic", "legacy"),
                     ("topic_title", '"Legacy (pre-v2) handoffs"'),
                     ("session_id", sid),
                     ("created", created),
                     ("kind", kind),
                     ("migrated_from", ".handoff/" + fn)):
        if key not in present and val:
            add.append("%s: %s" % (key, val))
    if not add:
        return raw
    return "\n".join([lines[0]] + add + lines[1:]).encode("utf-8")


def migrate_legacy():
    """Migrate legacy .handoff/*.md into handoffs/legacy/ with synthesized
    frontmatter. Idempotent and copy-before-delete (originals are untouched)."""
    legacy = legacy_dir()
    if not os.path.isdir(legacy):
        return
    marker = os.path.join(legacy, ".migrated")
    if os.path.isfile(marker):
        return
    md_files = [fn for fn in os.listdir(legacy)
                if fn.endswith(".md") and os.path.isfile(os.path.join(legacy, fn))]
    if not md_files:
        return
    target = topic_dir("legacy")
    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        return
    failed = False

    for fn in sorted(md_files):
        if not re.match(r"^" + TS_RE, fn):
            continue                         # skip README, .migrated, etc.
        f = os.path.join(legacy, fn)
        dest = os.path.join(target, fn)
        if os.path.isfile(dest):
            continue                         # idempotent: already copied
        if not os.access(f, os.R_OK):
            failed = True                    # unreadable: defer finalizing
            continue

        kind = "auto" if is_auto(fn) else "manual"
        stem = fn[:-3]
        if stem.endswith("-auto"):
            stem = stem[:-5]
        m = re.match(r"^(" + TS_RE + r")", stem)
        ts = m.group(1) if m else ""
        sid = stem[len(ts):]
        if sid.startswith("-"):
            sid = sid[1:]
        created = _ts_to_iso(ts)

        # Binary throughout: copy bytes verbatim and never decode (a non-UTF-8
        # legacy file must not crash migration), and treat a failed write as a
        # deferred failure so .migrated is not finalized prematurely.
        try:
            with open(f, "rb") as fh:
                raw = fh.read()
        except OSError:
            failed = True
            continue

        first_line = raw.split(b"\n", 1)[0].rstrip(b"\r")
        if first_line == b"---":
            # Already carries frontmatter: keep it, but backfill the schema-2 keys
            # discovery needs so the migrated copy is actually findable.
            if not atomic_write_bytes(dest, _normalize_legacy_fm(raw, sid, created, kind, fn)):
                failed = True
        else:
            fm = ["---", "schema: 2", "topic: legacy",
                  'topic_title: "Legacy (pre-v2) handoffs"']
            if sid:
                fm.append("session_id: " + sid)
            if created:
                fm.append("created: " + created)
            fm.append("kind: " + kind)
            fm.append("migrated_from: .handoff/" + fn)
            fm.append("---")
            fm.append("")
            blob = ("\n".join(fm) + "\n").encode("utf-8") + raw
            if not atomic_write_bytes(dest, blob):
                failed = True

    # Only finalize once every copy succeeded — a partial run leaves the marker
    # unwritten so the next call retries the stragglers.
    if not failed:
        atomic_write(marker, "migrated_at=%s\n" % now_ms())
        readme = os.path.join(legacy, "README.md")
        if not os.path.isfile(readme):
            try:
                with open(readme, "w") as f:
                    f.write(_LEGACY_README)
            except OSError:
                pass

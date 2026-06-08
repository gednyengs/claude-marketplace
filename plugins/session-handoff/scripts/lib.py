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
    return True


def bootstrap(argv, *, strict):
    """Parse leading trusted flags and init the context. Returns (ok, rest)."""
    project, plugin_data, rest = split_leading_flags(argv)
    ok = init_context(project, plugin_data, strict=strict)
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


def topic_dir(slug):
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


def session_short(payload=None):
    """Filename-safe short id: up to 12 alphanumerics. THE identity key."""
    return re.sub(r"[^a-zA-Z0-9]", "", session_id(payload))[:12]


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
    """Read-modify-write preserving other keys."""
    lines = []
    if os.path.isfile(path):
        try:
            with open(path) as f:
                lines = [ln for ln in f.read().split("\n")
                         if ln and not ln.startswith(key + "=")]
        except OSError:
            lines = []
    lines.append("%s=%s" % (key, value))
    atomic_write(path, "\n".join(lines) + "\n")


# --- Session->topic map and per-session state -------------------------------

def session_topic_file(sid):
    return os.path.join(sessions_dir(), sid + ".topic")


def session_topic_get(sid):
    try:
        with open(session_topic_file(sid)) as f:
            return f.read()
    except OSError:
        return ""


def session_topic_set(sid, topic):
    ensure_state()
    atomic_write(session_topic_file(sid), topic)


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


def ptr_file():
    return os.path.join(cwd_dir(), cwd_hash() + ".ptr")


def clears_file():
    return os.path.join(cwd_dir(), cwd_hash() + ".clears")


def cwd_lock():
    return os.path.join(cwd_dir(), cwd_hash() + ".lock")


def ptr_topic():
    return kv_get(ptr_file(), "topic")


def _ptr_set(topic, sid):
    ensure_state()
    f = ptr_file()
    kv_set(f, "topic", topic)
    kv_set(f, "last_sid", sid)
    kv_set(f, "updated_at", str(now_ms()))


def ptr_set(topic, sid):
    with_lock(cwd_lock(), _ptr_set, topic, sid)


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


def is_auto(name):
    return bool(_AUTO_RE.match(name or ""))


def is_manual(name):
    name = name or ""
    return bool(_MANUAL_RE.match(name)) and not is_auto(name)


def new_handoff_path(mode, sid, slug):
    suffix = "-auto" if mode == "auto" else ""
    return os.path.join(topic_dir(slug), "%s-%s%s.md" % (timestamp(), sid, suffix))


def fm_get(path, key):
    """Read a scalar frontmatter field (strips surrounding double quotes).
    Deliberately dumb: scans only the first --- block, no YAML semantics."""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return ""
    if not lines or lines[0] != "---":
        return ""
    prefix = re.compile(r"^" + re.escape(key) + r":[ \t]*")
    for ln in lines[1:]:
        if ln == "---":
            break
        if prefix.match(ln):
            val = prefix.sub("", ln, count=1)
            if val.startswith('"'):
                val = val[1:]
            if val.endswith('"'):
                val = val[:-1]
            return val
    return ""


def handoff_id(path):
    """Canonical id: "<topic>/<ts>-<sid>" (sid-qualified)."""
    base = os.path.basename(path)
    stem = base[:-3] if base.endswith(".md") else base
    if stem.endswith("-auto"):
        stem = stem[:-5]
    topic = fm_get(path, "topic") or os.path.basename(os.path.dirname(path))
    return "%s/%s" % (topic, stem)


def all_handoffs_bytime():
    """All handoff files, oldest->newest by timestamp prefix (across topics)."""
    d = handoff_dir()
    if not os.path.isdir(d):
        return []
    files = []
    for dirpath, _dirs, filenames in os.walk(d):
        for fn in filenames:
            if fn.endswith(".md"):
                files.append((fn, os.path.join(dirpath, fn)))
    files.sort(key=lambda t: (t[0], t[1]))
    return [p for _b, p in files]


def latest_for_session(sid):
    result = ""
    for f in all_handoffs_bytime():
        if fm_get(f, "session_id") == sid:
            result = f
    return result


def latest_auto_for_session(sid):
    result = ""
    for f in all_handoffs_bytime():
        if is_auto(os.path.basename(f)) and fm_get(f, "session_id") == sid:
            result = f
    return result


def latest_manual_in_topic(slug):
    d = topic_dir(slug)
    if not os.path.isdir(d):
        return ""
    cands = sorted(fn for fn in os.listdir(d)
                   if fn.endswith(".md") and is_manual(fn))
    return os.path.join(d, cands[-1]) if cands else ""


def recent_topics(limit=5):
    """Up to `limit` most recent topics, newest first: (base, topic, path).
    One row per topic, representative = its newest MANUAL handoff."""
    d = handoff_dir()
    if not os.path.isdir(d):
        return []
    rows = []
    for dirpath, _dirs, filenames in os.walk(d):
        for fn in filenames:
            if fn.endswith(".md") and is_manual(fn):
                p = os.path.join(dirpath, fn)
                rows.append((fn, fm_get(p, "topic"), p))
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
        if (not topic or not stem or topic in (".", "..")
                or "/" in stem or os.sep in topic or os.sep in stem):
            return ""
        for cand in (os.path.join(d, topic, stem + ".md"),
                     os.path.join(d, topic, stem + "-auto.md")):
            if os.path.isfile(cand) and _within_handoffs(cand):
                return cand
        matches = sorted(g for g in glob.glob(os.path.join(d, topic, stem + "*.md"))
                         if _within_handoffs(g))
        return matches[0] if len(matches) == 1 else ""
    if not q or q in (".", "..") or os.sep in q:
        return ""
    f = latest_manual_in_topic(q)
    return f if (f and _within_handoffs(f)) else ""


def handoff_when(base):
    """Reformat a basename's timestamp prefix to "YYYY-MM-DD HH:MM"."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})\d{2}", base or "")
    return "%s %s:%s" % (m.group(1), m.group(2), m.group(3)) if m else ""


def handoff_summary(path):
    """One-line task summary from a handoff's "## Task & progress" section."""
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
    base = slugify(text)
    if not base:
        base = "topic-" + timestamp()
    slug = base
    n = 2
    while os.path.isdir(topic_dir(slug)):
        slug = "%s-%d" % (base, n)
        n += 1
    return slug


# --- Deterministic project facts --------------------------------------------

def git(*args):
    try:
        r = subprocess.run(["git", "-C", project_dir(), *args],
                           capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def in_git():
    try:
        r = subprocess.run(["git", "-C", project_dir(), "rev-parse",
                            "--is-inside-work-tree"], capture_output=True, text=True)
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
    else:
        out.append("- _Not a git repository._")
    out.append("")
    out.append("## Environment & commands")
    out.append("")
    out.append(detect_commands())
    return "\n".join(out)


def rel(path):
    """Strip the project-dir prefix for tidy display paths."""
    base = project_dir() + os.sep
    return path[len(base):] if path.startswith(base) else path


# --- Age-based GC sweep -----------------------------------------------------

def gc_sweep(ttl_days=14):
    """Reclaim stale ephemeral state (incl. crash/kill leaks). Throttled ~1/hr."""
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
            if not atomic_write_bytes(dest, raw):    # already carries frontmatter: copy verbatim
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

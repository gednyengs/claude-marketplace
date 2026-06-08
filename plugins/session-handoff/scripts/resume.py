#!/usr/bin/env python3
# Load a topic's latest handoff. Resolution order (first match wins):
#   1. explicit <id|topic> argument
#   2. the session's recorded topic
#   3. a pending post-/clear baton for this session
#   4. the only recent topic
#   5. several recent topics -> print a picker (no state change)
# Cases 1-4 record the adopted topic; the picker changes nothing.
#
# Usage: resume.py --project-dir <dir> [--plugin-data <dir>] [--auto] [<id|topic>]
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


def emit_loaded(f, how, sid):
    topic = lib.fm_get(f, "topic") or os.path.basename(os.path.dirname(f))
    if not lib.session_is_degraded(sid):
        lib.session_topic_set(sid, topic)
        lib.pending_clear_clear(sid)
    lib.ptr_set(topic, sid)
    out = ["Source: %s (topic: %s — %s)" % (lib.rel(f), topic, how), ""]
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            out.append(fh.read())
    except OSError:
        pass
    print("\n".join(out))


def main():
    _ok, rest = lib.bootstrap(sys.argv[1:], strict=True)
    sid = lib.session_short()
    lib.gc_sweep()
    lib.migrate_legacy()

    # Ignore --auto (governs model behavior, not resolution); first remaining
    # token is an explicit <id|topic>.
    arg = ""
    for a in rest:
        if a == "--auto":
            continue
        if not arg:
            arg = a

    # ---- 1. Explicit id/topic argument ----
    if arg:
        f = lib.resolve_id(arg)
        if f and os.path.isfile(f):
            emit_loaded(f, 'requested "%s"' % arg, sid)
            return
        print('_No handoff matches "%s". Run /session-handoff:list to see what\'s available._' % arg)
        return

    # ---- 2. The session's own recorded topic ----
    if not lib.session_is_degraded(sid):
        mytopic = lib.session_topic_get(sid)
        if mytopic:
            f = lib.latest_manual_in_topic(mytopic)
            if f and os.path.isfile(f):
                emit_loaded(f, "this session's topic", sid)
                return
        # ---- 3. A claimed clear-baton (the post-/clear happy path) ----
        pend = lib.pending_clear_topic(sid)
        if pend:
            f = lib.latest_manual_in_topic(pend)
            if f and os.path.isfile(f):
                emit_loaded(f, "resumed after /clear", sid)
                return

    # ---- 4 & 5. Fall back to recent topics ----
    topics = lib.recent_topics(5)
    if len(topics) == 0:
        print("_No handoff found under %s. Run /session-handoff:save to create one._"
              % lib.rel(lib.handoff_dir()))
        return
    if len(topics) == 1:
        f = topics[0][2]
        if f and os.path.isfile(f):
            emit_loaded(f, "only recent topic", sid)
            return

    # ---- 5. Several topics: present a picker, mutate nothing ----
    out = ["PICK: multiple topics in this project. Choose one to resume (newest first):", ""]
    i = 0
    for base, topic, path in topics:
        if not topic:
            continue
        i += 1
        ttl = lib.fm_get(path, "topic_title") or topic
        when = lib.handoff_when(base) or "unknown time"
        summ = lib.handoff_summary(path) or "(no task summary)"
        out.append("%d. [%s] %s (%s)" % (i, when, ttl, topic))
        out.append("     id: " + lib.handoff_id(path))
        out.append("     " + summ)
    out.append("")
    out.append("_Reply with a number to resume that topic. Under --auto, entry 1 (newest) is loaded automatically._")
    print("\n".join(out))


main()

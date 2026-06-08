#!/usr/bin/env python3
# Print any handoff for reference without changing the session's current topic.
# If the loaded handoff is from a different topic, its id is recorded so the next
# save notes it as a depends_on cross-topic reference.
#
# Usage: load.py --project-dir <dir> [--plugin-data <dir>] <id|topic>
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


def main():
    _ok, rest = lib.bootstrap(sys.argv[1:], strict=True)
    sid = lib.session_short()
    lib.gc_sweep()
    lib.migrate_legacy()

    arg = rest[0] if rest else ""
    if not arg:
        print("_Usage: /session-handoff:load <id|topic>. Run /session-handoff:list to see ids._")
        return

    f = lib.resolve_id(arg)
    if not f or not os.path.isfile(f):
        print('_No handoff matches "%s". Run /session-handoff:list --any to see all topics._' % arg)
        return

    hid = lib.handoff_id(f)
    loaded_topic = lib.fm_get(f, "topic") or os.path.basename(os.path.dirname(f))

    # Record a cross-topic dependency only when the loaded topic differs from ours.
    if not lib.session_is_degraded(sid):
        if loaded_topic != lib.session_topic_get(sid):
            lib.deps_add(sid, hid)

    out = ["Source: %s (loaded %s)" % (lib.rel(f), hid), ""]
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            out.append(fh.read())
    except OSError:
        pass
    print("\n".join(out))


main()

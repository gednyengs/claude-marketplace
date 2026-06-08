#!/usr/bin/env python3
# SessionEnd hook. On /clear, leave a small "baton" carrying this session's topic
# so the next session can pick it back up. State is reclaimed by an age-based
# sweep, never deleted here (a resumed session keeps its id and its topic).
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


def body():
    payload = sys.stdin.read()
    ok, _rest = lib.bootstrap(sys.argv[1:], strict=False)
    if not ok:
        return
    sid = lib.session_short(payload)
    reason = lib.payload_field(payload, "reason")
    lib.gc_sweep()

    if reason == "clear" and not lib.session_is_degraded(sid):
        topic = lib.session_topic_get(sid)
        # Only leave a baton if this session was actually on a topic worth continuing.
        if topic:
            lib.clears_append(sid, topic)


lib.run_hook(body)

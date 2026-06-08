#!/usr/bin/env python3
# Stop hook. If this session's latest auto-snapshot still has unfilled
# "<!-- TODO -->" placeholders, block the stop and ask the model to finish it —
# at most twice (a per-session counter). Silent otherwise.
# (The printed block decision is normal output, not an error.)
import json
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
    if lib.session_is_degraded(sid):
        return

    # Only ever consider THIS session's own auto-snapshot.
    latest = lib.latest_auto_for_session(sid)
    if not latest or not os.path.isfile(latest):
        return

    lib.ensure_state()
    counter = os.path.join(lib.state_dir(), "enforce.%s.count" % sid)
    lock = os.path.join(lib.state_dir(), "enforce.%s.lock" % sid)

    def decide():
        # Serialized check-and-increment. Returns True => block; False => allow.
        try:
            with open(latest, encoding="utf-8", errors="replace") as f:
                has_todo = "<!-- TODO" in f.read()
        except OSError:
            has_todo = False
        if not has_todo:
            lib._unlink(counter)            # filled in: reset, allow stop
            return False
        n = 0
        try:
            with open(counter) as f:
                txt = f.read().strip()
            n = int(txt) if txt.isdigit() else 0
        except OSError:
            n = 0
        if n >= 2:
            lib._unlink(counter)            # gave up after 2: never trap the user
            return False
        try:
            with open(counter, "w") as f:
                f.write(str(n + 1))
        except OSError:
            pass
        return True

    if not lib.with_lock(lock, decide):
        return

    rel = lib.rel(latest)
    reason = ('The auto-generated handoff at %s still has unfilled "<!-- TODO -->" placeholders. '
              "Open it and replace each one with concrete detail (task & progress, key decisions, "
              "open questions/blockers, next steps, resume instructions) from this session, then "
              "stop." % rel)
    print(json.dumps({"decision": "block", "reason": reason}))


lib.run_hook(body)

#!/usr/bin/env python3
# Note which agents are running. The hooks module (hooks/register.ts) runs this
# just before /session-handoff:save, with {"session_id", "agents"} on stdin: the
# listing Claude Code gave it. new-path.py prints it moments later, so the
# handoff's "Agents & messages in flight" section starts from what is running
# rather than from what the model remembers starting.
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


def body():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    ok, _rest = lib.bootstrap(sys.argv[1:], strict=False)
    if not ok:
        return
    sid = data.get("session_id")
    sid = lib.short_id(sid if isinstance(sid, str) else "")
    if sid:
        lib.module_mark(sid)
        lib.agents_write(sid, data.get("agents"))


if __name__ == "__main__":          # importable for tests; the module runs it as a script
    lib.run_hook(body)

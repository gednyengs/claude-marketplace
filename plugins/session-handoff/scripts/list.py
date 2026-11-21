#!/usr/bin/env python3
# Browse handoffs (read-only).
#   default : handoffs in the current topic, newest first, up to MAX (default 5).
#   --any   : the latest handoff per topic across all topics, up to MAX.
# With no current topic, falls back to the all-topics view.
#
# Usage: list.py --project-dir <dir> [--plugin-data <dir>] [MAX] [--any]
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


def row(f):
    # Summaries are read out of committed files: flatten before display.
    base = os.path.basename(f)
    when = lib.handoff_when(base) or "unknown time"
    summ = lib.sanitize_line(lib.handoff_summary(f)) or "(no task summary)"
    kind = "auto" if lib.is_auto(base) else "manual"
    return ["- %s · %s · %s" % (lib.handoff_id(f), when, kind), "    " + summ]


def main():
    _ok, rest = lib.bootstrap(sys.argv[1:], strict=True)
    sid = lib.session_short()
    lib.gc_sweep(keep_sid=sid)
    lib.migrate_legacy()

    # A bare integer is MAX; --any switches to the cross-topic view.
    max_n = 5
    any_flag = False
    for a in rest:
        if a == "--any":
            any_flag = True
        elif a.isdigit():
            max_n = int(a)
        # ignore non-numeric noise / empty

    # The current topic is the SESSION's own topic (the cwd pointer is only a hint).
    cur = "" if lib.session_is_degraded(sid) else lib.safe_slug(lib.session_topic_get(sid))

    out = []
    # --- All-topics view (explicit --any, or no current topic) ---
    if any_flag or not cur:
        if not any_flag:
            out.append("_No current topic for this session — showing the latest per topic across the project._")
        topics = lib.recent_topics(max_n)
        if not topics:
            print("_No handoffs found. Run /session-handoff:save to create one._")
            return
        out.append("Topics (latest handoff each, newest first):")
        for base, topic, path in topics:
            if not path:
                continue
            ttl = lib.sanitize_line(lib.fm_get(path, "topic_title")) or topic
            out.append("")
            out.append("**%s** (%s)" % (ttl, topic))
            out.extend(row(path))
        print("\n".join(out))
        return

    # --- Current-topic view ---
    d = lib.topic_dir(cur)          # `cur` is already laundered through safe_slug
    files = ([f for f in sorted(glob.glob(os.path.join(d, "*.md")), reverse=True)
              if lib.is_handoff_name(os.path.basename(f))
              and lib._within_handoffs(f) and not lib.is_pending(f)][:max_n]
             if os.path.isdir(d) else [])
    if not files:
        print("_No handoffs yet in the current topic '%s'. Run /session-handoff:list --any to see other topics._" % cur)
        return
    out.append("Handoffs in topic '%s' (newest first):" % cur)
    out.append("")
    for f in files:
        if os.path.isfile(f):
            out.extend(row(f))
    print("\n".join(out))

if __name__ == "__main__":          # importable for tests; commands run it as a script
    main()

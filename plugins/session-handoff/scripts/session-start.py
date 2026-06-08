#!/usr/bin/env python3
# SessionStart hook — inject a short context note based on the start source:
#   resume  -> nothing (the transcript is already restored)
#   compact -> nudge to continue in-flight work (auto) or a pointer (manual)
#   clear   -> recap the topic that was just cleared and offer to resume it
#   startup -> a short list of recent topics
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


def topic_list():
    lines = []
    for base, topic, path in lib.recent_topics(5):
        if not topic:
            continue
        ttl = lib.fm_get(path, "topic_title") or topic
        lines.append("  - %s (%s) — %s" % (ttl, topic, lib.handoff_when(base)))
    return "\n".join(lines)


def emit(text):
    # cap injected context to keep per-turn cost low
    sys.stdout.write(text[:6000])
    sys.stdout.write("\n")


def body():
    payload = sys.stdin.read()
    ok, _rest = lib.bootstrap(sys.argv[1:], strict=False)
    if not ok:
        return
    sid = lib.session_short(payload)
    src = lib.payload_field(payload, "source")
    lib.gc_sweep()
    lib.migrate_legacy()

    if src == "resume":
        return

    if src == "compact":
        trig = lib.compact_trigger(sid)
        snap = lib.latest_auto_for_session(sid)
        lib.compact_clear(sid)
        if trig == "auto":
            lines = ["[session-handoff] Auto-compaction occurred mid-task; the conversation was summarized."]
            if snap:
                lines.append("Pre-compaction snapshot: %s." % lib.rel(snap))
            lines.append("Continue your in-flight work from where you left off "
                         "(see the snapshot's Next steps if you need them).")
            emit("\n".join(lines))
        elif snap:
            print("[session-handoff] Context compacted. Snapshot if needed: %s." % lib.rel(snap))
        return

    if src == "clear":
        if lib.session_is_degraded(sid):
            return
        claimed = lib.clears_claim(sid, 120)
        if claimed == "AMBIGUOUS":
            emit("=== session-handoff: context cleared; multiple recent clears in this directory. ===\n"
                 "Run /session-handoff:resume to pick which topic to continue.")
        elif claimed:
            parts = claimed.split("\t")
            ctopic = parts[0]
            csid = parts[1] if len(parts) > 1 else ""
            cts = parts[2] if len(parts) > 2 else ""
            lib.pending_clear_set(sid, ctopic, csid, cts)
            latest = lib.latest_manual_in_topic(ctopic)
            title = ctopic
            summ = ""
            if latest:
                t = lib.fm_get(latest, "topic_title")
                if t:
                    title = t
                summ = lib.handoff_summary(latest)
            lines = ['=== session-handoff: you cleared while working on topic "%s" (%s). ===' % (title, ctopic)]
            if summ:
                lines.append("Last: " + summ)
            lines.append("Run /session-handoff:resume to continue it, or start fresh.")
            emit("\n".join(lines))
        else:
            lst = topic_list()
            if lst:
                emit("=== session-handoff: context cleared. Recent topics: ===\n" + lst +
                     "\nRun /session-handoff:resume to continue one.")
        return

    # startup / default
    lst = topic_list()
    if lst:
        emit("=== session-handoff: recent topics in this project ===\n" + lst +
             "\nRun /session-handoff:resume to continue one, or ignore if starting fresh.")


lib.run_hook(body)

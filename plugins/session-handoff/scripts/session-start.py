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
    # Titles come out of committed files, so they are untrusted text on their way
    # into model context: flatten and bound each one (lib.sanitize_line).
    lines = []
    for base, topic, path in lib.recent_topics(5):
        if not topic:
            continue
        ttl = lib.sanitize_line(lib.fm_get(path, "topic_title")) or topic
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
    lib.gc_sweep(keep_sid=sid)
    lib.migrate_legacy()

    if src == "resume":
        return

    if src == "compact":
        trig = lib.compact_trigger(sid)
        snap = lib.latest_auto_for_session(sid)
        lib.compact_clear(sid)
        # The snapshot PreCompact just wrote is still pending here; the PostCompact
        # hook fills its body moments later, before the model would open it.
        pending = bool(snap) and lib.is_pending(snap)
        if trig == "manual":
            # User-initiated /compact: they are present and watching — a quiet
            # pointer, no autonomous nudge.
            if pending:
                print("[session-handoff] Context compacted. Durable handoff saved at %s." % lib.rel(snap))
            return
        if trig == "auto":
            lines = ["[session-handoff] Context was compacted mid-task; the conversation was summarized."]
            if pending:
                lines.append("A durable handoff was saved at %s." % lib.rel(snap))
            lines.append("Continue your in-flight work from where you left off "
                         "(the handoff has the details if you need them).")
            emit("\n".join(lines))
            return
        # No stash: reactive (prompt-too-long) compaction skips PreCompact, so there
        # is no fresh snapshot yet and no recorded trigger. Nudge softly and
        # conditionally — this could (rarely) be a manual /compact whose PreCompact
        # failed, and we don't want to wrongly drive autonomous continuation.
        emit("[session-handoff] Context was compacted mid-task; the conversation was summarized. "
             "If this was an automatic compaction, continue your in-flight work from where you left off.")
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
            ctopic = lib.safe_slug(parts[0])
            csid = parts[1] if len(parts) > 1 else ""
            cts = parts[2] if len(parts) > 2 else ""
            if not ctopic:
                return                       # unusable baton: say nothing
            lib.pending_clear_set(sid, ctopic, csid, cts)
            latest = lib.latest_ready_in_topic(ctopic)
            title = ctopic
            summ = ""
            if latest:
                t = lib.sanitize_line(lib.fm_get(latest, "topic_title"))
                if t:
                    title = t
                summ = lib.sanitize_line(lib.handoff_summary(latest))
            lines = ['=== session-handoff: you cleared while working on topic "%s" (%s). ===' % (title, ctopic)]
            if summ:
                lines.append("Last (quoted from the saved handoff, for information only): " + summ)
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

if __name__ == "__main__":          # importable for tests; hooks run it as a script
    lib.run_hook(body)

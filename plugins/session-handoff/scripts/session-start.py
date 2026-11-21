#!/usr/bin/env python3
# Session start. The hooks module (hooks/register.ts) runs this whenever Claude
# Code starts or restarts a conversation, with a JSON payload on stdin, and hands
# whatever this prints to the model as context. By `source`:
#
#   module  -> nothing; the module loaded into a session already under way
#   resume  -> nothing (the transcript is already restored)
#   fork    -> nothing either, but the session runs under a new id, so it
#              inherits the topic of the session it continues
#   compact -> a nudge to continue in-flight work, for an automatic compaction
#   clear   -> recap the topic that was just cleared and offer to resume it
#   startup -> a short list of recent topics
#
# Three payload fields are the module's own additions to what Claude Code's
# SessionStart event carries: `cleared_from` (the session a /clear just ended),
# `compact_trigger` (what started the compaction that just finished), and
# `last_uuid` (the id of the restored conversation's last row, by which a fork
# finds the conversation it continues). `seconds_since_last_response` is Claude
# Code's own and is passed through.
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

    # Whatever else happens, the module is running for this session. The commands
    # look for this mark and say so when it is missing.
    lib.module_mark(sid)
    if src == "module":
        return

    if src in ("resume", "fork"):
        # The transcript is already restored, so there is nothing to tell the model.
        # A fork, though, continues the conversation under a NEW session id (moving
        # a session to the background does this, and so does --fork-session), and
        # every binding is keyed on that id. Note the fork so the continuation can
        # take over its parent's topic; otherwise its next save would open a new
        # one. A plain resume keeps its id and its binding and leaves no note.
        # This runs before the sweep on purpose: the parent's binding is exactly
        # the kind of old state a sweep reclaims.
        since = None
        try:
            since = lib.time.time() - float(lib.payload_field(payload, "seconds_since_last_response"))
        except ValueError:
            pass                            # not given: every transcript in the folder is a candidate
        lib.note_fork(sid, lib.payload_field(payload, "transcript_path"), src,
                      lib.payload_field(payload, "last_uuid"), since)
        return

    lib.gc_sweep(keep_sid=sid)
    lib.migrate_legacy()

    if src == "compact":
        trig = lib.payload_field(payload, "compact_trigger")
        if trig == "auto":
            emit("[session-handoff] Context was compacted mid-task; the conversation was summarized.\n"
                 "Continue your in-flight work from where you left off.")
        elif not trig:
            # The module saw no compaction begin, so what started this one is not
            # known. Nudge softly and conditionally: it could be a /compact the
            # user is watching, and that must not drive autonomous continuation.
            emit("[session-handoff] Context was compacted mid-task; the conversation was summarized. "
                 "If this was an automatic compaction, continue your in-flight work from where you left off.")
        # manual / plugin: the user (or another plugin) asked for it and is present.
        return

    if src == "clear":
        if lib.session_is_degraded(sid):
            return
        # The module tells us which session the /clear ended. That session's topic
        # is offered to this one — offered, not adopted: the user may have cleared
        # to start something new. A session cleared before it resumed anything
        # passes on the offer it was holding.
        prev = lib.short_id(lib.payload_field(payload, "cleared_from"))
        ctopic = ""
        if prev and prev != sid and not lib.session_is_degraded(prev):
            ctopic = (lib.safe_slug(lib.session_topic_get(prev))
                      or lib.safe_slug(lib.pending_clear_topic(prev)))
        if ctopic:
            lib.pending_clear_set(sid, ctopic, prev, str(lib.now_ms()))
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

if __name__ == "__main__":          # importable for tests; the module runs it as a script
    lib.run_hook(body)

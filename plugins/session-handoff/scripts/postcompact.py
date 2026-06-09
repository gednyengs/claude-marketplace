#!/usr/bin/env python3
# PostCompact hook. Claude Code has just produced its compaction summary and
# passes it to us as `compact_summary`. We persist that summary as the durable
# handoff body so it survives /clear (Claude Code's in-context copy does not).
#
# Normal path: complete the *pending* safety snapshot PreCompact just wrote
# (flip status: pending -> complete and fill the body). Reactive prompt-too-long
# compaction skips PreCompact, so when no pending snapshot exists we create a
# completed handoff from scratch. We find the skeleton by recency rather than a
# stashed path because SessionStart(source=compact) — which runs *before* us —
# has already cleared the compaction stash.
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402

WRAP_HEADER = "## Compaction summary (auto-generated)"


def compose(fm_lines, summary, trigger):
    note = ("> Persisted verbatim from Claude Code's compaction summary "
            "(trigger: %s) so it survives /clear and restarts." % trigger)
    body = [
        "# Handoff — " + lib.iso(),
        "",
        WRAP_HEADER,
        "",
        note,
        "",
        (summary or "").strip(),
        "",
        lib.facts(),
    ]
    return "\n".join(fm_lines + [""] + body) + "\n"


def body():
    payload = sys.stdin.read()
    ok, _rest = lib.bootstrap(sys.argv[1:], strict=False)
    if not ok:
        return
    sid = lib.session_short(payload)
    trigger = lib.payload_field(payload, "trigger") or "auto"
    summary = lib.payload_field(payload, "compact_summary")
    if not summary.strip():
        return  # nothing to persist

    # Prefer to complete the pending skeleton PreCompact just wrote (seconds ago).
    # The freshness guard avoids filling a STALE pending skeleton left by an earlier
    # aborted compaction: in that case (e.g. a later reactive compaction, which skips
    # PreCompact) we want a fresh handoff, not this summary backdated onto the old file.
    target = lib.latest_auto_for_session(sid)
    fresh_pending = False
    if target and lib.is_pending(target):
        try:
            fresh_pending = (time.time() - os.path.getmtime(target)) < 1800  # 30 min
        except OSError:
            fresh_pending = False
    if fresh_pending:
        slug = lib.fm_get(target, "topic") or os.path.basename(os.path.dirname(target))
        title = lib.fm_get(target, "topic_title") or slug
        created = lib.fm_get(target, "created") or lib.created_stamp()
    else:
        # Reactive / no skeleton: create a fresh completed handoff.
        slug = lib.session_topic_get(sid)
        if not slug:
            slug = lib.unique_topic_slug("topic-" + lib.timestamp())
            lib.session_topic_set(sid, slug)
        title = slug
        latest = lib.latest_ready_in_topic(slug)
        if latest:
            t = lib.fm_get(latest, "topic_title")
            if t:
                title = t
        created = lib.created_stamp()
        target = lib.new_handoff_path("auto", sid, slug)

    fm = [
        "---",
        "schema: 2",
        "topic: " + slug,
        "topic_title: " + lib.fm_quote(title),
        "session_id: " + sid,
        "created: " + created,
        "kind: auto",
        "status: complete",
        "compact_trigger: " + trigger,
        "---",
    ]
    if lib.atomic_write(target, compose(fm, summary, trigger)):
        print("[session-handoff] Compaction summary persisted to %s." % lib.rel(target))


lib.run_hook(body)

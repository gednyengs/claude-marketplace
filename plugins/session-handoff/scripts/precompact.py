#!/usr/bin/env python3
# PreCompact hook. Before the context is compacted, write a *pending* safety
# snapshot (frontmatter + repo snapshot + detected commands) for this session's
# topic, stash the compaction trigger so SessionStart can tell auto from manual,
# and steer Claude Code's own compaction summary toward handoff-relevant content.
#
# The snapshot's BODY is filled in moments later by the PostCompact hook, which
# receives Claude Code's generated compaction summary and persists it here
# (flipping status: pending -> complete). The no-tools summarizer cannot edit
# files during compaction, so we never ask the model to fill the file by hand.
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
    trigger = lib.payload_field(payload, "trigger") or "auto"

    # Resolve this session's topic; lazily create a provisional one if it has none.
    slug = lib.session_topic_get(sid)
    if not slug:
        slug = lib.unique_topic_slug("topic-" + lib.timestamp())
        lib.session_topic_set(sid, slug)

    # Best-effort human title (carried from an earlier handoff in this topic).
    title = slug
    latest = lib.latest_ready_in_topic(slug)
    if latest:
        t = lib.fm_get(latest, "topic_title")
        if t:
            title = t

    f = lib.new_handoff_path("auto", sid, slug)
    content = "\n".join([
        "---",
        "schema: 2",
        "topic: " + slug,
        "topic_title: " + lib.fm_quote(title),
        "session_id: " + sid,
        "created: " + lib.created_stamp(),
        "kind: auto",
        "status: pending",
        "compact_trigger: " + trigger,
        "---",
        "",
        "# Handoff — " + lib.iso(),
        "",
        "> Auto-snapshot taken before context compaction (trigger: %s)." % trigger,
        "> Claude Code's compaction summary is persisted into this file once compaction",
        "> completes; until then this is a repo-state safety record.",
        "",
        lib.facts(),
    ])
    lib.atomic_write(f, content + "\n")

    # Stash the trigger so SessionStart(source=compact) can tell auto from manual.
    lib.compact_set(sid, trigger, lib.now_ms())

    # Steer Claude Code's compaction summary. Our stdout is appended to the
    # summarizer's instructions AFTER any /compact text the user supplied
    # (Claude Code concatenates them) — additive, never exclusive — so we phrase
    # it to defer to a deliberately narrow user request.
    print("When you write the compaction summary, in addition to anything the user asked you to "
          "focus on above, ensure it preserves — where present — these handoff essentials so work "
          "can resume cleanly in a fresh session: the exact in-flight step quoted verbatim (the "
          "edit or command underway); key decisions and the rationale behind them; open questions "
          "and blockers; and the files/functions touched and why. Do not broaden the scope of an "
          "explicitly narrow user request; within that scope, capture these where they apply.")


lib.run_hook(body)

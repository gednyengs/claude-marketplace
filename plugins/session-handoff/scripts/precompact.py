#!/usr/bin/env python3
# PreCompact hook. Before the context is compacted, write a topic-tagged
# auto-snapshot (with TODO placeholders), record the compaction trigger, and ask
# the model to fill the snapshot in — emphasizing the in-flight step.
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

    # Best-effort human title (carried from an earlier manual handoff).
    title = slug
    latest = lib.latest_manual_in_topic(slug)
    if latest:
        t = lib.fm_get(latest, "topic_title")
        if t:
            title = t

    f = lib.new_handoff_path("auto", sid, slug)
    content = "\n".join([
        "---",
        "schema: 2",
        "topic: " + slug,
        'topic_title: "%s"' % title,
        "session_id: " + sid,
        "created: " + lib.created_stamp(),
        "kind: auto",
        "compact_trigger: " + trigger,
        "---",
        "",
        "# Handoff — " + lib.iso(),
        "",
        "> AUTO-SNAPSHOT written before context compaction (trigger: %s)." % trigger,
        "> Replace each <!-- TODO --> with concrete detail from the live conversation.",
        "",
        "## Task & progress",
        "<!-- TODO: current goal; what's done; what's in progress; what's not started -->",
        "",
        "## Key decisions & rationale",
        "<!-- TODO: important choices and *why*, so they aren't relitigated -->",
        "",
        "## Open questions & blockers",
        "<!-- TODO: unresolved questions, things waiting on input, known risks -->",
        "",
        "## Next steps",
        "<!-- TODO: ordered & actionable; put the IN-FLIGHT step (the edit/command you were "
        "mid-way through) FIRST -->",
        "",
        lib.facts(),
        "",
        "## Resume instructions",
        "<!-- TODO: the first concrete actions the next turn should take to continue -->",
    ])
    lib.atomic_write(f, content + "\n")

    # Stash the trigger so SessionStart(source=compact) can tell auto from manual.
    lib.compact_set(sid, trigger, lib.now_ms())

    print("[session-handoff] A safety snapshot was saved to %s before compaction." % lib.rel(f))
    print('Before this context is compacted, replace every "<!-- TODO -->" in that file with concrete')
    print("detail from this conversation — especially the IN-FLIGHT step (the edit or command you were")
    print("mid-way through) as the FIRST item under Next steps, so work resumes mid-stride. Keep it")
    print("concise but sufficient for a session with no memory of this one. Do not include secrets.")


lib.run_hook(body)

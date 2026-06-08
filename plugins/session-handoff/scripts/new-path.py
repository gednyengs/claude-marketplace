#!/usr/bin/env python3
# Resolve the topic and print the destination path + frontmatter block for a new
# handoff. Performs no state changes — those are committed by save-record.py once
# the file is written, so an aborted write loses nothing.
#
# Usage: new-path.py --project-dir <dir> [--plugin-data <dir>] [--topic <slug>] [note...]
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


def main():
    _ok, rest = lib.bootstrap(sys.argv[1:], strict=True)
    sid = lib.session_short()
    lib.gc_sweep()
    lib.migrate_legacy()

    # Parse --topic <slug> (or --topic=slug); everything else is the note.
    topic_arg = ""
    note_parts = []
    i, n = 0, len(rest)
    while i < n:
        a = rest[i]
        if a == "--topic" and i + 1 < n:
            topic_arg = rest[i + 1]; i += 2; continue
        if a.startswith("--topic="):
            topic_arg = a[len("--topic="):]; i += 1; continue
        if a == "--":
            i += 1; continue
        note_parts.append(a); i += 1
    note = " ".join(note_parts)

    # Resolve the topic: --topic > session's recorded topic > new topic.
    is_new = False
    if topic_arg:
        slug = lib.slugify(topic_arg) or lib.unique_topic_slug(topic_arg)
    else:
        recorded = lib.session_topic_get(sid)
        if recorded:
            slug = recorded
        else:
            slug = lib.unique_topic_slug(note or ("topic-" + lib.timestamp()))
            is_new = True

    # Title: carry an existing topic's title; else derive from the note.
    title = slug
    latest = lib.latest_manual_in_topic(slug)
    if latest:
        t = lib.fm_get(latest, "topic_title")
        if t:
            title = t
    elif note:
        title = note

    # depends_on: pending cross-topic deps, filtered to OTHER topics.
    deps = [d for d in lib.deps_read(sid) if d and not d.startswith(slug + "/")]

    created = lib.created_stamp()
    path = lib.new_handoff_path("manual", sid, slug)
    try:
        os.makedirs(lib.topic_dir(slug), exist_ok=True)
    except OSError:
        pass

    out = ["PATH: " + path, "TOPIC: " + slug]
    if lib.session_is_degraded(sid):
        out.append("NOTE: session id unavailable — handoff is not session-tagged for provenance.")
    out.append("")
    out.append("Begin the file with EXACTLY this frontmatter block (you may refine topic_title to a "
               "concise human title), then write the body sections beneath it:")
    out.append("---")
    out.append("schema: 2")
    out.append("topic: " + slug)
    out.append('topic_title: "%s"' % title)
    out.append("session_id: " + sid)
    out.append("created: " + created)
    out.append("kind: manual")
    if note:
        out.append('note: "%s"' % note)
    if deps:
        out.append("depends_on:")
        out.extend("  - " + d for d in deps)
    out.append("---")

    if is_new:
        pend = lib.pending_clear_topic(sid)
        if pend and pend != slug:
            out.append("")
            out.append("NOTICE: Starting new topic '%s'. You recently cleared topic '%s' — re-run with "
                       "`--topic %s` to continue that one instead." % (slug, pend, pend))
    print("\n".join(out))


main()

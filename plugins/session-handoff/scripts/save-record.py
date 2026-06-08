#!/usr/bin/env python3
# Record a saved handoff: set the session's topic, refresh the per-directory
# pointer, and clear consumed pending state. Run after the handoff file is
# written; it verifies the file before recording. Idempotent.
#
# Usage: save-record.py --project-dir <dir> [--plugin-data <dir>] <path> <topic-slug>
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


def main():
    _ok, rest = lib.bootstrap(sys.argv[1:], strict=True)
    path = rest[0] if len(rest) >= 1 else ""
    slug = rest[1] if len(rest) >= 2 else ""
    if not path or not slug:
        sys.stderr.write("save-record: usage: save-record.py <path> <topic-slug>\n")
        sys.exit(2)

    # Confirm the handoff was actually written as expected BEFORE clearing pending
    # state — a misfired/wrong-path commit must not discard pending cross-topic links.
    if not os.path.isfile(path):
        sys.stderr.write("save-record: '%s' not found — write the handoff first; not recording.\n" % path)
        sys.exit(1)
    ftopic = lib.fm_get(path, "topic")
    if ftopic != slug:
        sys.stderr.write("save-record: %s has topic '%s', expected '%s' — not recording.\n" % (path, ftopic, slug))
        sys.exit(1)
    if lib.fm_get(path, "kind") != "manual":
        sys.stderr.write("save-record: %s is not a manual handoff — not recording.\n" % path)
        sys.exit(1)

    sid = lib.session_short()

    # The session now belongs to this topic (skip for a degraded/unidentified
    # session so it can't contaminate the shared 'nosession' key).
    if not lib.session_is_degraded(sid):
        lib.session_topic_set(sid, slug)

    lib.ptr_set(slug, sid)        # refresh the durable per-directory pointer
    lib.deps_clear(sid)           # deps are now in the file's frontmatter
    lib.pending_clear_clear(sid)  # the baton (if any) has been honored

    print("Recorded: topic=%s session=%s" % (slug, sid))


main()

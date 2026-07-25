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

    if not lib.valid_slug(slug):
        sys.stderr.write("save-record: '%s' is not a valid topic slug — not recording.\n" % slug)
        sys.exit(1)

    # Confirm the handoff was actually written as expected BEFORE clearing pending
    # state — a misfired/wrong-path commit must not discard pending cross-topic links.
    if not os.path.isfile(path):
        sys.stderr.write("save-record: '%s' not found — write the handoff first; not recording.\n" % path)
        sys.exit(1)
    if not lib._within_handoffs(path):
        sys.stderr.write("save-record: '%s' is outside the handoff directory — not recording.\n" % path)
        sys.exit(1)
    fm = lib.fm_all(path)
    ftopic = fm.get("topic", "")
    if ftopic != slug:
        sys.stderr.write("save-record: %s has topic '%s', expected '%s' — not recording.\n" % (path, ftopic, slug))
        sys.exit(1)
    if fm.get("kind") != "manual":
        sys.stderr.write("save-record: %s is not a manual handoff — not recording.\n" % path)
        sys.exit(1)

    sid = lib.session_short()

    # The session now belongs to this topic (skip for a degraded/unidentified
    # session so it can't contaminate the shared 'nosession' key). A failed state
    # write is reported rather than swallowed: the handoff file is on disk either
    # way, but without the binding the next /save would start a new topic.
    if not lib.session_is_degraded(sid):
        if not lib.session_topic_set(sid, slug):
            sys.stderr.write(
                "save-record: handoff written, but the session->topic binding could not be saved "
                "(state dir not writable: %s). Re-run /session-handoff:save with `--topic %s` to "
                "stay on this topic.\n" % (lib.state_dir(), slug))
            sys.exit(1)

    lib.deps_clear(sid)           # deps are now in the file's frontmatter
    lib.pending_clear_clear(sid)  # the baton (if any) has been honored

    print("Recorded: topic=%s session=%s" % (slug, sid))
    notice = lib.ignored_notice(path)
    if notice:
        print("NOTICE: " + notice)

if __name__ == "__main__":          # importable for tests; commands run it as a script
    main()

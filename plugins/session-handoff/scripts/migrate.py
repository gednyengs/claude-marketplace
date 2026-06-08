#!/usr/bin/env python3
# Migrate legacy .handoff/*.md handoffs into handoffs/legacy/ with synthesized
# frontmatter. Idempotent and copy-before-delete (originals are left untouched).
# Migration also runs automatically from the other scripts; this is for running
# it by hand.
#
# Usage: migrate.py --project-dir <dir> [--plugin-data <dir>]
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402


def main():
    lib.bootstrap(sys.argv[1:], strict=True)
    legacy = lib.legacy_dir()
    target = lib.topic_dir("legacy")

    if not os.path.isdir(legacy):
        print("Nothing to migrate — no legacy %s directory." % lib.rel(legacy))
        return

    def count_md(d):
        return len(glob.glob(os.path.join(d, "*.md"))) if os.path.isdir(d) else 0

    before = count_md(target)
    lib.migrate_legacy()
    after = count_md(target)
    added = after - before

    if os.path.isfile(os.path.join(legacy, ".migrated")):
        if added > 0:
            print("Migrated %d legacy handoff(s) into %s." % (added, lib.rel(target)))
        else:
            print("Already migrated — %s is up to date (%d file(s))." % (lib.rel(target), after))
        print("Originals are kept under %s (copy-before-delete); delete them once verified." % lib.rel(legacy))
    else:
        print("Migration did not complete (some copies failed). Re-run to retry; originals are untouched.")
        sys.exit(1)


main()

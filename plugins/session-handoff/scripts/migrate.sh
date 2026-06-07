#!/usr/bin/env bash
# Standalone v1 -> v2 migration (see docs/V2-SPEC.md §9).
#
# Copies legacy .handoff/*.md handoffs into handoffs/legacy/ with synthesized
# schema-2 frontmatter. Idempotent and copy-before-delete: originals are left in
# place, a second run is a no-op. This also runs opportunistically from the hooks
# and command scripts (hb_migrate_legacy); this wrapper is for running it by hand.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

legacy="$(hb_legacy_dir)"
target="$(hb_topic_dir legacy)"

if [ ! -d "$legacy" ]; then
  echo "Nothing to migrate — no legacy $(hb_rel "$legacy") directory."
  exit 0
fi

before=0
[ -d "$target" ] && before="$(find "$target" -type f -name '*.md' 2>/dev/null | grep -c .)"

hb_migrate_legacy

after=0
[ -d "$target" ] && after="$(find "$target" -type f -name '*.md' 2>/dev/null | grep -c .)"
added=$(( after - before ))

if [ -f "$legacy/.migrated" ]; then
  if [ "$added" -gt 0 ]; then
    echo "Migrated $added legacy handoff(s) into $(hb_rel "$target")."
  else
    echo "Already migrated — $(hb_rel "$target") is up to date ($after file(s))."
  fi
  echo "Originals are kept under $(hb_rel "$legacy") (copy-before-delete); delete them once verified."
else
  echo "Migration did not complete (some copies failed). Re-run to retry; originals are untouched."
  exit 1
fi
exit 0

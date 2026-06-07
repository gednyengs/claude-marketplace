#!/usr/bin/env bash
# /save — commit side effects (see docs/V2-SPEC.md §6.1 step 4).
#
# Run by the model AFTER it has written the handoff file. Splitting this from the
# pre-write resolution (new-path.sh) guarantees that pending cross-topic deps are
# only cleared once they've actually been persisted into the written frontmatter —
# an aborted write loses nothing. All operations are idempotent.
#
# Usage: save-record.sh <path> <topic-slug>
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

path="${1:-}"; slug="${2:-}"
if [ -z "$path" ] || [ -z "$slug" ]; then
  echo "save-record: usage: save-record.sh <path> <topic-slug>" >&2
  exit 2
fi

# Confirm the handoff was actually written as expected BEFORE clearing pending state
# (deps / clear-baton). This prevents a misfired or wrong-path commit from discarding
# pending cross-topic links — the whole point of splitting prep from commit.
if [ ! -f "$path" ]; then
  echo "save-record: '$path' not found — write the handoff first; not recording." >&2
  exit 1
fi
ftopic="$(hb_fm_get "$path" topic)"
if [ "$ftopic" != "$slug" ]; then
  echo "save-record: $path has topic '$ftopic', expected '$slug' — not recording." >&2
  exit 1
fi
if [ "$(hb_fm_get "$path" kind)" != "manual" ]; then
  echo "save-record: $path is not a manual handoff — not recording." >&2
  exit 1
fi

sid="$(hb_session_short)"

# The session now belongs to this topic (skip for a degraded/unidentified session
# so it can't contaminate the shared 'nosession' key — the cwd pointer still
# carries continuity for this directory).
hb_session_is_degraded "$sid" || hb_session_topic_set "$sid" "$slug"

# Refresh the durable "active topic here" pointer (locked, atomic RMW).
hb_ptr_set "$slug" "$sid"

# Deps are now in the file's frontmatter; the baton (if any) has been honored.
hb_deps_clear "$sid"
hb_pending_clear_clear "$sid"

echo "Recorded: topic=$slug session=$sid"
exit 0

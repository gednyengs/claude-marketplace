#!/usr/bin/env bash
# /session-handoff:load <id|topic> — pull any handoff into context (see §6.3).
#
# Unlike /resume, /load does NOT change the session's primary topic and never
# touches the cwd pointer. If the loaded handoff belongs to a DIFFERENT topic than
# the session's own, its id is appended to sessions/<sid>.deps so the next /save
# records it as a `depends_on` cross-topic reference. Same-topic loads are already
# in the chain and are not recorded.
#
# Output: "Source: <rel> (loaded <id>)\n\n<file>"  or  a "_not found_" line.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

sid="$(hb_session_short)"
hb_gc_sweep >/dev/null 2>&1
hb_migrate_legacy >/dev/null 2>&1

arg="${1:-}"
if [ -z "$arg" ]; then
  echo "_Usage: /session-handoff:load <id|topic>. Run /session-handoff:list to see ids._"
  exit 0
fi

f="$(hb_resolve_id "$arg")"
if [ -z "$f" ] || [ ! -f "$f" ]; then
  echo "_No handoff matches \"$arg\". Run /session-handoff:list --any to see all topics._"
  exit 0
fi

id="$(hb_handoff_id "$f")"
loaded_topic="$(hb_fm_get "$f" topic)"; [ -n "$loaded_topic" ] || loaded_topic="$(basename "$(dirname "$f")")"

# Record a cross-topic dependency only when the loaded topic differs from ours.
if ! hb_session_is_degraded "$sid"; then
  mytopic="$(hb_session_topic_get "$sid")"
  if [ "$loaded_topic" != "$mytopic" ]; then
    hb_deps_add "$sid" "$id"
  fi
fi

echo "Source: $(hb_rel "$f") (loaded ${id})"
echo
cat "$f"
exit 0

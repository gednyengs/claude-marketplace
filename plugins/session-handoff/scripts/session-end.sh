#!/usr/bin/env bash
# SessionEnd hook (see docs/V2-SPEC.md §8.2). Cleanup-only; not blockable.
#   reason=clear -> append a clear-baton (carrying THIS session's own topic) so
#                   the post-/clear session can pick the right topic back up.
# No eager GC of session->topic state: a cleared/exited session keeps the SAME
# session_id under --resume, so deleting its mapping would mis-bucket a later
# /save. All reclamation is age-based (lib.sh hb_gc_sweep).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

input="$(cat 2>/dev/null)"
sid="$(hb_session_short "$input")"
reason="$(hb_payload_field "$input" reason)"

hb_gc_sweep >/dev/null 2>&1

if [ "$reason" = "clear" ] && ! hb_session_is_degraded "$sid"; then
  topic="$(hb_session_topic_get "$sid")"
  # Only leave a baton if this session was actually on a topic worth continuing.
  [ -n "$topic" ] && hb_clears_append "$sid" "$topic"
fi
exit 0

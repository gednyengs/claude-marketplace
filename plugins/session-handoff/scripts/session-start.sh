#!/usr/bin/env bash
# SessionStart hook: fires when a session begins, resumes, or restarts after
# compaction. If a handoff exists, inject its content so Claude automatically
# knows where work stopped. Output is bounded to keep token cost low.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

# Capture the hook payload so we can read the guaranteed session id.
input="$(cat 2>/dev/null)"
sid="$(hb_session_short "$input")"

# Prefer this session's own latest handoff (auto or manual). This is what makes
# a post-compaction or resumed session pick up exactly where it left off. Skip this
# when the session is unidentified, so degraded sessions don't adopt each other's
# handoffs from the shared "nosession" bucket.
own=""
hb_session_is_degraded "$sid" || own="$(hb_latest_for "$sid")"
if [ -n "${own:-}" ] && [ -f "${own:-}" ]; then
  echo "=== session-handoff: most recent handoff for this session ($(hb_rel "$own")) ==="
  echo
  # Cap output so a large handoff can't blow up the session budget.
  head -c 6000 "$own"
  echo
  echo
  echo "=== Run /session-handoff:resume to continue from here, or ignore if starting fresh. ==="
  exit 0
fi

# No handoff for this session yet (fresh, forked, or a teammate's clone). Surface
# the newest *manual* handoff as an FYI — but never imply it describes this task.
other="$(hb_manual_handoffs | tail -1)"
if [ -n "${other:-}" ] && [ -f "${other:-}" ]; then
  echo "=== session-handoff: a handoff from another session exists ($(hb_rel "$other")) ==="
  echo "=== Review it — do NOT assume it describes your task. Run /session-handoff:resume to load it. ==="
  echo
  head -c 2000 "$other"
  echo
fi
exit 0

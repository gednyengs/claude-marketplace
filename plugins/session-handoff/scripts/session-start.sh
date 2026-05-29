#!/usr/bin/env bash
# SessionStart hook: fires when a session begins, resumes, or restarts after
# compaction. If a handoff exists, inject its content so Claude automatically
# knows where work stopped. Output is bounded to keep token cost low.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

# Capture the hook payload so we can read the guaranteed session id and start source.
input="$(cat 2>/dev/null)"
sid="$(hb_session_short "$input")"

# Start source: "startup" | "resume" | "clear" | "compact" (best-effort).
src=""
if command -v jq >/dev/null 2>&1; then
  src="$(printf '%s' "$input" | jq -r '.source // empty' 2>/dev/null)"
fi
[ -n "$src" ] || src="$(_hb_json_field "$input" source)"

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

# No handoff for this session yet (fresh, forked, teammate's clone — or a just-cleared
# session, which gets a new session id). Point to /resume rather than injecting content:
# passively adopting the newest manual handoff could be the wrong workstream. /resume is
# permissive and lets the user pick. Path-only — no foreign content enters this context.
other="$(hb_manual_handoffs | tail -1)"
if [ -n "${other:-}" ] && [ -f "${other:-}" ]; then
  if [ "$src" = "clear" ]; then
    echo "=== session-handoff: context was cleared. Recent checkpoints exist (most recent: $(hb_rel "$other")). ==="
    echo "=== Run /session-handoff:resume to pick one up. ==="
  else
    echo "=== session-handoff: a recent handoff exists (most recent: $(hb_rel "$other")). ==="
    echo "=== Run /session-handoff:resume to review and choose one (it may be from another session). ==="
  fi
fi
exit 0

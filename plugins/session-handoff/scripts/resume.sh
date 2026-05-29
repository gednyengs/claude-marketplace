#!/usr/bin/env bash
# Prints the most recent handoff in full, for the /session-handoff:resume command.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

# Slash commands have no stdin payload; fall back to the session-id env var.
sid="$(hb_session_short)"

# Prefer this session's own latest handoff — unambiguous, no contamination. Skip
# when unidentified so a degraded session can't claim another's "nosession" handoff.
own=""
hb_session_is_degraded "$sid" || own="$(hb_latest_for "$sid")"
if [ -n "${own:-}" ] && [ -f "${own:-}" ]; then
  echo "Source: $(hb_rel "$own") (this session)"
  echo
  cat "$own"
  exit 0
fi

# No handoff tagged for this session (post-/clear, fresh, forked, concurrent, or a
# teammate's clone). Choose from the portable manual handoffs. /resume is explicit
# user intent, so these are valid to load — we just disambiguate when there's more
# than one candidate.
total="$(hb_recent_manual 9999 | grep -c .)"

if [ "$total" -eq 0 ]; then
  echo "_No handoff found in $(hb_rel "$(hb_handoff_dir)"). Run /session-handoff:save to create one._"
  exit 0
fi

if [ "$total" -eq 1 ]; then
  # Exactly one checkpoint — just load it (this is the common save -> /clear -> resume case).
  only="$(hb_recent_manual 1)"
  tag="$(hb_handoff_sid "$(basename "$only")")"; tag="${tag:-legacy}"
  echo "Source: $(hb_rel "$only") (portable handoff; saved in session ${tag})"
  echo
  cat "$only"
  exit 0
fi

# Two or more candidates: present a picker and do NOT load anything yet.
echo "PICK: no handoff is tagged for this session. Recent handoffs to resume (newest first):"
echo
i=0
hb_recent_manual 5 | while IFS= read -r f; do
  i=$((i + 1))
  base="$(basename "$f")"
  tag="$(hb_handoff_sid "$base")"; tag="${tag:-legacy}"
  when="$(hb_handoff_when "$base")"; [ -n "$when" ] || when="unknown time"
  summ="$(hb_handoff_summary "$f")"; [ -n "$summ" ] || summ="(no task summary)"
  echo "$i. [$when · session $tag] $summ"
  echo "     $(hb_rel "$f")"
done
[ "$total" -gt 5 ] && { echo; echo "_(showing 5 of $total — ask to resume a specific path for an older one)_"; }
echo
echo "_Reply with a number to load that handoff. Under --auto, entry 1 (newest) is loaded automatically._"
exit 0

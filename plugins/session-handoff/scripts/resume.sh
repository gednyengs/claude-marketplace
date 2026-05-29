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

# Otherwise offer the portable manual handoffs from other sessions to choose from.
manual="$(hb_manual_handoffs)"
if [ -z "${manual:-}" ]; then
  echo "_No handoff found in $(hb_rel "$(hb_handoff_dir)"). Run /session-handoff:save to create one._"
  exit 0
fi

echo "_No handoff for this session yet. Manual handoffs from other sessions (newest last):_"
echo
echo "$manual" | while IFS= read -r f; do echo "- $(hb_rel "$f")"; done
echo
newest="$(echo "$manual" | tail -1)"
echo "_Showing the newest below; ask to resume a specific path to load a different one._"
echo
echo "Source: $(hb_rel "$newest") (another session — verify it matches your task)"
echo
cat "$newest"
exit 0

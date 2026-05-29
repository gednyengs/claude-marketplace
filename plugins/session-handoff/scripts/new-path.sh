#!/usr/bin/env bash
# Prints the exact path the /session-handoff:save command should write the new
# handoff to. The filename is tagged with this session's id so concurrent saves
# in the same project never collide, while the file stays a portable (manual)
# handoff that any session or teammate can resume.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

# No stdin payload in a slash command; session id comes from the environment.
sid="$(hb_session_short)"
mkdir -p "$(hb_handoff_dir)" 2>/dev/null

# Keep stdout to a single machine-usable path; any advisory goes to stderr.
if hb_session_is_degraded "$sid"; then
  echo "NOTE: session id unavailable — this handoff is not session-tagged for provenance." >&2
fi
hb_new_handoff_path manual "$sid"
exit 0
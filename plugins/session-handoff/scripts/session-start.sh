#!/usr/bin/env bash
# SessionStart hook: fires when a session begins, resumes, or restarts after
# compaction. If a handoff exists, inject its content so Claude automatically
# knows where work stopped. Output is bounded to keep token cost low.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

# Drain stdin (hook payload) so we don't block.
cat >/dev/null 2>&1

latest="$(hb_latest_handoff)"
[ -z "${latest:-}" ] && exit 0
[ -f "${latest:-}" ] || exit 0

echo "=== session-handoff: most recent handoff ($(hb_rel "$latest")) ==="
echo
# Cap output so a large handoff can't blow up the session budget.
head -c 6000 "$latest"
echo
echo
echo "=== Run /session-handoff:resume to continue from here, or ignore if starting fresh. ==="
exit 0

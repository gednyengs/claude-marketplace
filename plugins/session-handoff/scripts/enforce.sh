#!/usr/bin/env bash
# Stop hook: makes the auto-snapshot actually get filled in.
# If the newest handoff is an unfilled AUTO snapshot (still has TODO markers),
# block the stop once or twice and ask Claude to complete it. Silent in all
# other cases. Capped via a counter in the plugin data dir to avoid loops.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

input="$(cat 2>/dev/null)"  # capture hook payload for the session id

# Enforcement needs jq to emit a structured decision; degrade silently without it.
command -v jq >/dev/null 2>&1 || exit 0

sid="$(hb_session_short "$input")"
# Never trap a session we can't identify — its counter/snapshot would be shared.
hb_session_is_degraded "$sid" && exit 0

# Only ever consider *this* session's own auto-snapshot, so one session's
# pending compaction can never block an unrelated session's stop.
latest="$(hb_latest_auto_for "$sid")"
[ -n "${latest:-}" ] || exit 0
[ -f "${latest:-}" ] || exit 0

data="${CLAUDE_PLUGIN_DATA:-$(hb_handoff_dir)}"
mkdir -p "$data" 2>/dev/null
counter="$data/enforce.${sid}.count"
lock="$data/enforce.${sid}.lock"

# Serialize the check-and-increment so concurrent Stop hooks can't lose updates.
# flock is best-effort: if it's unavailable (e.g. macOS), fd 9 is just an open
# file and we proceed unlocked — session-scoping already removes cross-session
# contention, so the residual same-session race is benign.
exec 9>"$lock" 2>/dev/null
command -v flock >/dev/null 2>&1 && flock -x 9 2>/dev/null

# If no "<!-- TODO -->" placeholder markers remain, it's been filled: reset and allow stop.
# (Match the marker specifically, not the word "TODO", which also appears in the banner.)
if ! grep -q "<!-- TODO" "$latest" 2>/dev/null; then
  rm -f "$counter" 2>/dev/null
  exit 0
fi

n=0
[ -f "$counter" ] && n="$(cat "$counter" 2>/dev/null || echo 0)"
case "$n" in ''|*[!0-9]*) n=0 ;; esac

if [ "$n" -ge 2 ]; then
  # Give up after 2 nudges so we never trap the user.
  rm -f "$counter" 2>/dev/null
  exit 0
fi
echo $((n + 1)) > "$counter" 2>/dev/null

rel="$(hb_rel "$latest")"
jq -n --arg f "$rel" '{
  decision: "block",
  reason: ("The auto-generated handoff at " + $f + " still has unfilled \"<!-- TODO -->\" placeholders. Open it and replace each one with concrete details (task & progress, key decisions, open questions/blockers, next steps, resume instructions) drawn from this session, then stop.")
}'
exit 0

#!/usr/bin/env bash
# Stop hook (see docs/V2-SPEC.md §8.4). If THIS session's own latest auto-snapshot
# still has unfilled "<!-- TODO -->" placeholders, block the stop and ask the model
# to finish it — capped at 2 nudges via a per-session counter. Silent otherwise.
# jq is NOT required: the decision JSON is emitted directly.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

input="$(cat 2>/dev/null)"
sid="$(hb_session_short "$input")"
hb_session_is_degraded "$sid" && exit 0

# Only ever consider THIS session's own auto-snapshot.
latest="$(hb_latest_auto_for_session "$sid")"
[ -n "$latest" ] && [ -f "$latest" ] || exit 0

hb_ensure_state
counter="$(hb_state_dir)/enforce.${sid}.count"
lock="$(hb_state_dir)/enforce.${sid}.lock"

# Serialize check-and-increment. Returns 0 ⇒ should block; 1 ⇒ allow stop.
_enforce_decide() {
  if ! grep -q "<!-- TODO" "$latest" 2>/dev/null; then
    rm -f "$counter" 2>/dev/null; return 1          # filled in: reset, allow stop
  fi
  local n=0
  [ -f "$counter" ] && n="$(cat "$counter" 2>/dev/null || echo 0)"
  case "$n" in ''|*[!0-9]*) n=0 ;; esac
  if [ "$n" -ge 2 ]; then
    rm -f "$counter" 2>/dev/null; return 1          # gave up after 2: never trap the user
  fi
  echo $((n + 1)) > "$counter" 2>/dev/null
  return 0
}

hb_with_lock "$lock" _enforce_decide || exit 0

rel="$(hb_rel "$latest")"
printf '{"decision":"block","reason":"The auto-generated handoff at %s still has unfilled \\"<!-- TODO -->\\" placeholders. Open it and replace each one with concrete detail (task & progress, key decisions, open questions/blockers, next steps, resume instructions) from this session, then stop."}\n' "$rel"
exit 0

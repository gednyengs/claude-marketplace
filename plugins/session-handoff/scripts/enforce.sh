#!/usr/bin/env bash
# Stop hook: makes the auto-snapshot actually get filled in.
# If the newest handoff is an unfilled AUTO snapshot (still has TODO markers),
# block the stop once or twice and ask Claude to complete it. Silent in all
# other cases. Capped via a counter in the plugin data dir to avoid loops.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

cat >/dev/null 2>&1  # drain stdin

# Enforcement needs jq to emit a structured decision; degrade silently without it.
command -v jq >/dev/null 2>&1 || exit 0

latest="$(hb_latest_handoff)"
[ -n "${latest:-}" ] || exit 0
[ -f "${latest:-}" ] || exit 0

# Only enforce auto-generated snapshots.
case "$latest" in
  *-auto.md) : ;;
  *) exit 0 ;;
esac

data="${CLAUDE_PLUGIN_DATA:-$(hb_handoff_dir)}"
mkdir -p "$data" 2>/dev/null
counter="$data/enforce.count"

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

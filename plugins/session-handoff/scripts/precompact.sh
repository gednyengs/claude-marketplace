#!/usr/bin/env bash
# PreCompact hook: fires right before Claude Code compacts the context window.
# Writes a deterministic safety-snapshot handoff (git + env facts) with TODO
# placeholders, then asks the model to enrich it from the live conversation
# while it still has full context.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

input="$(cat 2>/dev/null)"

trigger="auto"
if command -v jq >/dev/null 2>&1; then
  t="$(printf '%s' "$input" | jq -r '.trigger // empty' 2>/dev/null)"
  [ -n "$t" ] && trigger="$t"
fi

dir="$(hb_handoff_dir)"
mkdir -p "$dir" 2>/dev/null
file="$dir/$(hb_timestamp)-auto.md"

{
  echo "# Handoff — $(hb_iso)"
  echo
  echo "> AUTO-SNAPSHOT written before context compaction (trigger: ${trigger})."
  echo "> Sections marked TODO still need to be filled from the live conversation."
  echo
  echo "## Task & progress"
  echo "<!-- TODO: current goal; what's done; what's in progress; what's not started -->"
  echo
  echo "## Key decisions & rationale"
  echo "<!-- TODO: important choices and *why*, so they aren't relitigated -->"
  echo
  echo "## Open questions & blockers"
  echo "<!-- TODO: unresolved questions, things waiting on input, known risks -->"
  echo
  echo "## Next steps"
  echo "<!-- TODO: an ordered, actionable list -->"
  echo
  hb_facts
  echo
  echo "## Resume instructions"
  echo "<!-- TODO: the first concrete actions the next session should take -->"
} > "$file" 2>/dev/null

# This text is added to the model's context for the current (pre-compaction) turn.
cat <<EOF
[session-handoff] A safety snapshot was saved to $(hb_rel "$file") before compaction.
Before this context is compacted, open that file and replace every "<!-- TODO -->"
with concrete details from this conversation: task & progress, key decisions and why,
open questions/blockers, next steps, and resume instructions. Keep it concise but
sufficient for someone with no memory of this session to continue. Do not include secrets.
EOF
exit 0

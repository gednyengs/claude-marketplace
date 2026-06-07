#!/usr/bin/env bash
# PreCompact hook (see docs/V2-SPEC.md §8.3). Fires right before compaction.
# Writes a deterministic, topic-tagged auto-snapshot (with TODO placeholders),
# stashes the auto|manual trigger so SessionStart(compact) can branch, and asks
# the model to enrich the snapshot — emphasizing the IN-FLIGHT step.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

input="$(cat 2>/dev/null)"
sid="$(hb_session_short "$input")"
trigger="$(hb_payload_field "$input" trigger)"; [ -n "$trigger" ] || trigger="auto"

# Resolve this session's topic; lazily create a provisional one if it has none.
slug="$(hb_session_topic_get "$sid")"
if [ -z "$slug" ]; then
  slug="$(hb_unique_topic_slug "topic-$(hb_timestamp)")"
  hb_session_topic_set "$sid" "$slug"
fi

# Best-effort human title for the topic (carried from an earlier manual handoff).
title="$slug"
latest="$(hb_latest_manual_in_topic "$slug")"
[ -n "$latest" ] && { t="$(hb_fm_get "$latest" topic_title)"; [ -n "$t" ] && title="$t"; }

file="$(hb_new_handoff_path auto "$sid" "$slug")"

{
  echo "---"
  echo "schema: 2"
  echo "topic: ${slug}"
  echo "topic_title: \"${title}\""
  echo "session_id: ${sid}"
  echo "created: $(date +%Y-%m-%dT%H:%M:%S%z)"
  echo "kind: auto"
  echo "compact_trigger: ${trigger}"
  echo "---"
  echo
  echo "# Handoff — $(hb_iso)"
  echo
  echo "> AUTO-SNAPSHOT written before context compaction (trigger: ${trigger})."
  echo "> Replace each <!-- TODO --> with concrete detail from the live conversation."
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
  echo "<!-- TODO: ordered & actionable; put the IN-FLIGHT step (the edit/command you were mid-way through) FIRST -->"
  echo
  hb_facts
  echo
  echo "## Resume instructions"
  echo "<!-- TODO: the first concrete actions the next turn should take to continue -->"
} | hb_atomic_write "$file"

# Stash the trigger so SessionStart(source=compact) can tell auto from manual.
hb_compact_set "$sid" "$trigger" "$(hb_now_ms)"

cat <<EOF
[session-handoff] A safety snapshot was saved to $(hb_rel "$file") before compaction.
Before this context is compacted, replace every "<!-- TODO -->" in that file with concrete
detail from this conversation — especially the IN-FLIGHT step (the edit or command you were
mid-way through) as the FIRST item under Next steps, so work resumes mid-stride. Keep it
concise but sufficient for a session with no memory of this one. Do not include secrets.
EOF
exit 0

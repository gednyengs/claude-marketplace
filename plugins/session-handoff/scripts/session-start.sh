#!/usr/bin/env bash
# SessionStart hook — source-aware injection (see docs/V2-SPEC.md §8.1).
#   resume  -> no-op (CLI already restored the transcript)
#   compact -> auto: nudge to continue in-flight work; manual: light pointer
#   clear   -> claim a clear-baton and suggest the topic (never silently adopt)
#   startup -> bounded recent-topic list + pointer to /resume
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

input="$(cat 2>/dev/null)"
sid="$(hb_session_short "$input")"
src="$(hb_payload_field "$input" source)"

hb_gc_sweep >/dev/null 2>&1
hb_migrate_legacy >/dev/null 2>&1   # bring any v1 .handoff/ forward (idempotent no-op once done)

emit() { head -c 6000; echo; }   # cap injected context to keep per-turn cost low

_topic_list() {  # prints up to 5 recent topics as bullet lines
  hb_recent_topics 5 | while IFS="$(printf '\t')" read -r base topic path; do
    [ -n "$topic" ] || continue
    ttl="$(hb_fm_get "$path" topic_title)"; [ -n "$ttl" ] || ttl="$topic"
    echo "  - ${ttl} (${topic}) — $(hb_handoff_when "$base")"
  done
}

case "$src" in
  resume)
    exit 0 ;;

  compact)
    trig="$(hb_compact_trigger "$sid")"
    snap="$(hb_latest_auto_for_session "$sid")"
    hb_compact_clear "$sid"
    if [ "$trig" = "auto" ]; then
      {
        echo "[session-handoff] Auto-compaction occurred mid-task; the conversation was summarized."
        [ -n "$snap" ] && echo "Pre-compaction snapshot: $(hb_rel "$snap")."
        echo "Continue your in-flight work from where you left off (see the snapshot's Next steps if you need them)."
      } | emit
    else
      [ -n "$snap" ] && echo "[session-handoff] Context compacted. Snapshot if needed: $(hb_rel "$snap")."
    fi
    exit 0 ;;

  clear)
    hb_session_is_degraded "$sid" && exit 0
    claimed="$(hb_clears_claim "$sid" 120)"
    if [ "$claimed" = "AMBIGUOUS" ]; then
      {
        echo "=== session-handoff: context cleared; multiple recent clears in this directory. ==="
        echo "Run /session-handoff:resume to pick which topic to continue."
      } | emit
    elif [ -n "$claimed" ]; then
      # claimed = "<topic>\t<cleared_sid>\t<cleared_at_ms>" (full baton row).
      ctopic="$(printf '%s' "$claimed" | cut -f1)"
      csid="$(printf '%s' "$claimed" | cut -f2)"
      cts="$(printf '%s' "$claimed" | cut -f3)"
      hb_pending_clear_set "$sid" "$ctopic" "$csid" "$cts"
      latest="$(hb_latest_manual_in_topic "$ctopic")"
      title="$ctopic"
      [ -n "$latest" ] && { t="$(hb_fm_get "$latest" topic_title)"; [ -n "$t" ] && title="$t"; }
      summ=""; [ -n "$latest" ] && summ="$(hb_handoff_summary "$latest")"
      {
        echo "=== session-handoff: you cleared while working on topic \"${title}\" (${ctopic}). ==="
        [ -n "$summ" ] && echo "Last: ${summ}"
        echo "Run /session-handoff:resume to continue it, or start fresh."
      } | emit
    else
      list="$(_topic_list)"
      if [ -n "$list" ]; then
        { echo "=== session-handoff: context cleared. Recent topics: ==="; printf '%s\n' "$list"; \
          echo "Run /session-handoff:resume to continue one."; } | emit
      fi
    fi
    exit 0 ;;

  startup|*)
    list="$(_topic_list)"
    if [ -n "$list" ]; then
      { echo "=== session-handoff: recent topics in this project ==="; printf '%s\n' "$list"; \
        echo "Run /session-handoff:resume to continue one, or ignore if starting fresh."; } | emit
    fi
    exit 0 ;;
esac

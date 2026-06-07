#!/usr/bin/env bash
# /session-handoff:resume — load a topic's latest handoff (see docs/V2-SPEC.md §6.2).
#
# Resolution order (first match wins):
#   1. explicit <id|topic> arg              -> that handoff
#   2. sessions/<sid>.topic                 -> its latest manual handoff
#   3. sessions/<sid>.pending-clear baton   -> that topic's latest (post-/clear)
#   4. exactly one recent topic             -> its latest
#   5. several recent topics                -> PICK: a topic picker (no mutation)
#
# When a SINGLE handoff is resolved (cases 1–4) it is being loaded, so this script
# records the side effects of adopting that topic: sessions/<sid>.topic, the cwd
# pointer, and clearing the consumed .pending-clear baton. The picker (case 5)
# mutates nothing — the user re-runs `resume.sh <id>` to choose, hitting case 1.
#
# Output shapes (the command .md branches on these):
#   "Source: <rel> (topic: <slug> — <how>)\n\n<file>"   a handoff was loaded
#   "PICK: ..."                                          a topic picker
#   "_No handoff ..._"                                   nothing to resume
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

sid="$(hb_session_short)"
hb_gc_sweep >/dev/null 2>&1
hb_migrate_legacy >/dev/null 2>&1

# Args: ignore a --auto flag (that governs model behavior, not resolution); the
# first remaining token is an explicit <id|topic>.
arg=""
while [ $# -gt 0 ]; do
  case "$1" in
    --auto) ;;
    *) [ -z "$arg" ] && arg="$1" ;;
  esac
  shift
done

# Load a resolved handoff: record topic adoption, then print Source + contents.
_emit_loaded() {  # file  how
  local f="$1" how="$2" topic
  topic="$(hb_fm_get "$f" topic)"; [ -n "$topic" ] || topic="$(basename "$(dirname "$f")")"
  if ! hb_session_is_degraded "$sid"; then
    hb_session_topic_set "$sid" "$topic"
    hb_pending_clear_clear "$sid"
  fi
  hb_ptr_set "$topic" "$sid"
  echo "Source: $(hb_rel "$f") (topic: ${topic} — ${how})"
  echo
  cat "$f"
}

# ---- 1. Explicit id/topic argument --------------------------------------------
if [ -n "$arg" ]; then
  f="$(hb_resolve_id "$arg")"
  if [ -n "$f" ] && [ -f "$f" ]; then
    _emit_loaded "$f" "requested \"$arg\""
    exit 0
  fi
  echo "_No handoff matches \"$arg\". Run /session-handoff:list to see what's available._"
  exit 0
fi

# ---- 2. The session's own recorded topic --------------------------------------
if ! hb_session_is_degraded "$sid"; then
  mytopic="$(hb_session_topic_get "$sid")"
  if [ -n "$mytopic" ]; then
    f="$(hb_latest_manual_in_topic "$mytopic")"
    if [ -n "$f" ] && [ -f "$f" ]; then
      _emit_loaded "$f" "this session's topic"
      exit 0
    fi
  fi

  # ---- 3. A claimed clear-baton (the post-/clear happy path) -------------------
  pend="$(hb_pending_clear_topic "$sid")"
  if [ -n "$pend" ]; then
    f="$(hb_latest_manual_in_topic "$pend")"
    if [ -n "$f" ] && [ -f "$f" ]; then
      _emit_loaded "$f" "resumed after /clear"
      exit 0
    fi
  fi
fi

# ---- 4 & 5. Fall back to recent topics in this project ------------------------
topics="$(hb_recent_topics 5)"
count="$(printf '%s\n' "$topics" | grep -c .)"

if [ "${count:-0}" -eq 0 ]; then
  echo "_No handoff found under $(hb_rel "$(hb_handoff_dir)"). Run /session-handoff:save to create one._"
  exit 0
fi

if [ "${count:-0}" -eq 1 ]; then
  f="$(printf '%s\n' "$topics" | cut -f3)"
  if [ -n "$f" ] && [ -f "$f" ]; then
    _emit_loaded "$f" "only recent topic"
    exit 0
  fi
fi

# ---- 5. Several topics: present a picker, mutate nothing ----------------------
echo "PICK: multiple topics in this project. Choose one to resume (newest first):"
echo
i=0
printf '%s\n' "$topics" | while IFS="$(printf '\t')" read -r base topic path; do
  [ -n "$topic" ] || continue
  i=$((i + 1))
  ttl="$(hb_fm_get "$path" topic_title)"; [ -n "$ttl" ] || ttl="$topic"
  when="$(hb_handoff_when "$base")"; [ -n "$when" ] || when="unknown time"
  summ="$(hb_handoff_summary "$path")"; [ -n "$summ" ] || summ="(no task summary)"
  echo "$i. [$when] $ttl ($topic)"
  echo "     id: $(hb_handoff_id "$path")"
  echo "     $summ"
done
echo
echo "_Reply with a number to resume that topic. Under --auto, entry 1 (newest) is loaded automatically._"
exit 0

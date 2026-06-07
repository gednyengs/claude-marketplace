#!/usr/bin/env bash
# /session-handoff:list [MAX] [--any] — browse handoffs (see docs/V2-SPEC.md §6.4).
#
#   default : handoffs in the CURRENT topic, newest first, up to MAX (default 5).
#   --any   : the latest handoff per topic across ALL topics, up to MAX.
# Read-only. Each row carries an id usable with /load and /resume. If there is no
# current topic, falls back to the all-topics view with a note.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

sid="$(hb_session_short)"
hb_gc_sweep >/dev/null 2>&1
hb_migrate_legacy >/dev/null 2>&1

# Args: a bare integer is MAX; --any switches to the cross-topic view.
max=5; any=0
while [ $# -gt 0 ]; do
  case "$1" in
    --any) any=1 ;;
    *[!0-9]*) ;;                       # ignore non-numeric noise
    '') ;;
    *) max="$1" ;;
  esac
  shift
done

_row() {  # path
  local f="$1" base when summ kind
  base="$(basename "$f")"
  when="$(hb_handoff_when "$base")"; [ -n "$when" ] || when="unknown time"
  summ="$(hb_handoff_summary "$f")"; [ -n "$summ" ] || summ="(no task summary)"
  kind="manual"; hb_is_auto "$base" && kind="auto"
  echo "- $(hb_handoff_id "$f") · ${when} · ${kind}"
  echo "    ${summ}"
}

# The current topic is the SESSION's own topic (the cwd pointer is only a hint and
# may belong to another session's work — spec §7 — so it's not used here).
cur=""
hb_session_is_degraded "$sid" || cur="$(hb_session_topic_get "$sid")"

# --- All-topics view (explicit --any, or no current topic) ---------------------
if [ "$any" -eq 1 ] || [ -z "$cur" ]; then
  [ "$any" -eq 0 ] && echo "_No current topic for this session — showing the latest per topic across the project._"
  topics="$(hb_recent_topics "$max")"
  if [ -z "$topics" ]; then
    echo "_No handoffs found. Run /session-handoff:save to create one._"
    exit 0
  fi
  echo "Topics (latest handoff each, newest first):"
  printf '%s\n' "$topics" | while IFS="$(printf '\t')" read -r base topic path; do
    [ -n "$path" ] || continue
    ttl="$(hb_fm_get "$path" topic_title)"; [ -n "$ttl" ] || ttl="$topic"
    echo
    echo "**${ttl}** (${topic})"
    _row "$path"
  done
  exit 0
fi

# --- Current-topic view --------------------------------------------------------
dir="$(hb_topic_dir "$cur")"
files="$(ls -1 "$dir"/*.md 2>/dev/null | sort -r | head -n "$max")"
if [ -z "$files" ]; then
  echo "_No handoffs yet in the current topic '${cur}'. Run /session-handoff:list --any to see other topics._"
  exit 0
fi
echo "Handoffs in topic '${cur}' (newest first):"
echo
printf '%s\n' "$files" | while IFS= read -r f; do
  [ -f "$f" ] && _row "$f"
done
exit 0

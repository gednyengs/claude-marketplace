#!/usr/bin/env bash
# /save — resolution & frontmatter prep (see docs/V2-SPEC.md §6.1).
#
# PURE resolution: this script decides the topic and prints everything the model
# needs to write the handoff — the destination PATH, a verbatim frontmatter block
# (schema 2), and an optional NOTICE to relay. It deliberately performs NO state
# mutation: the session->topic map, cwd pointer, and .deps/.pending-clear are
# committed by save-record.sh AFTER the model has written the file, so an aborted
# write can never lose pending cross-topic deps.
#
# Usage: new-path.sh [--topic <slug>] [note words...]
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

sid="$(hb_session_short)"
hb_gc_sweep >/dev/null 2>&1
hb_migrate_legacy >/dev/null 2>&1

# --- Parse args: --topic <slug> (or --topic=slug), everything else is the note --
topic_arg=""; note=""
while [ $# -gt 0 ]; do
  case "$1" in
    --topic)   shift; topic_arg="${1:-}" ;;
    --topic=*) topic_arg="${1#--topic=}" ;;
    --)        ;;
    *)         note="${note:+$note }$1" ;;
  esac
  shift
done

# --- Resolve the topic: --topic  >  session's recorded topic  >  new topic ------
is_new=0
if [ -n "$topic_arg" ]; then
  # Explicit choice: use as-is (slugified). Joins an existing topic or starts it.
  slug="$(hb_slugify "$topic_arg")"; [ -n "$slug" ] || slug="$(hb_unique_topic_slug "$topic_arg")"
elif slug="$(hb_session_topic_get "$sid")" && [ -n "$slug" ]; then
  :                                   # session already belongs to a topic
else
  # New topic. Seed the slug from the note, else a timestamped placeholder.
  slug="$(hb_unique_topic_slug "${note:-topic-$(hb_timestamp)}")"
  is_new=1
fi

# --- Title: carry an existing topic's title; else derive from the note ----------
title="$slug"
latest="$(hb_latest_manual_in_topic "$slug")"
if [ -n "$latest" ]; then
  t="$(hb_fm_get "$latest" topic_title)"; [ -n "$t" ] && title="$t"
elif [ -n "$note" ]; then
  title="$note"
fi

# --- depends_on: pending cross-topic deps, filtered to OTHER topics -------------
deps="$(hb_deps_read "$sid" 2>/dev/null | while IFS= read -r d; do
  [ -n "$d" ] || continue
  case "$d" in "$slug"/*) ;; *) printf '%s\n' "$d" ;; esac
done)"

# --- Destination path -----------------------------------------------------------
created="$(date +%Y-%m-%dT%H:%M:%S%z)"
path="$(hb_new_handoff_path manual "$sid" "$slug")"
mkdir -p "$(hb_topic_dir "$slug")" 2>/dev/null

# --- Emit -----------------------------------------------------------------------
echo "PATH: $path"
echo "TOPIC: $slug"
hb_session_is_degraded "$sid" && echo "NOTE: session id unavailable — handoff is not session-tagged for provenance."
echo
echo "Begin the file with EXACTLY this frontmatter block (you may refine topic_title to a concise human title), then write the body sections beneath it:"
echo "---"
echo "schema: 2"
echo "topic: $slug"
echo "topic_title: \"$title\""
echo "session_id: $sid"
echo "created: $created"
echo "kind: manual"
[ -n "$note" ] && echo "note: \"$note\""
if [ -n "$deps" ]; then
  echo "depends_on:"
  printf '%s\n' "$deps" | while IFS= read -r d; do echo "  - $d"; done
fi
echo "---"

# --- Notice: creating a new topic while a clear-baton is pending ----------------
if [ "$is_new" -eq 1 ]; then
  pend="$(hb_pending_clear_topic "$sid" 2>/dev/null)"
  if [ -n "$pend" ] && [ "$pend" != "$slug" ]; then
    echo
    echo "NOTICE: Starting new topic '$slug'. You recently cleared topic '$pend' — re-run with \`--topic $pend\` to continue that one instead."
  fi
fi
exit 0

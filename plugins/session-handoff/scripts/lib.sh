#!/usr/bin/env bash
# ===========================================================================
# Shared helpers for the session-handoff plugin (v2 — topic model).
# Sourced by the hook scripts and the slash-command helper scripts.
#
# Design constraints (see docs/V2-SPEC.md):
#   - No `set -e`: a single failing git/awk call must never abort a hook.
#   - jq is NOT required. All ephemeral state is line-oriented (key=value or
#     TAB-delimited), so the plugin degrades gracefully without jq.
#   - Committed handoffs live under <project>/.claude/sekekama/session-handoff/.
#   - Ephemeral state lives in $CLAUDE_PLUGIN_DATA (out of the repo), or a
#     gitignored in-repo .state/ fallback. It is reclaimed by age, never by
#     eager deletion on exit (so --resume and crash/kill stay correct).
# ===========================================================================

# --- Project & committed paths ---------------------------------------------

hb_project_dir() { echo "${CLAUDE_PROJECT_DIR:-$(pwd)}"; }

# Plugin root inside the project (org-namespaced, under .claude/).
hb_root() { echo "$(hb_project_dir)/.claude/sekekama/session-handoff"; }

# Where committed handoffs live.
hb_handoff_dir() { echo "$(hb_root)/handoffs"; }

# Directory for a given topic's handoffs.
hb_topic_dir() { echo "$(hb_handoff_dir)/$1"; }

# Legacy v1 handoff dir (for migration detection).
hb_legacy_dir() { echo "$(hb_project_dir)/.handoff"; }

# --- Ephemeral state paths --------------------------------------------------

# Out-of-repo when CLAUDE_PLUGIN_DATA is set; else an in-repo gitignored fallback.
hb_state_dir() {
  if [ -n "${CLAUDE_PLUGIN_DATA:-}" ]; then
    echo "$CLAUDE_PLUGIN_DATA"
  else
    echo "$(hb_root)/.state"
  fi
}

hb_sessions_dir() { echo "$(hb_state_dir)/sessions"; }
hb_cwd_dir()      { echo "$(hb_state_dir)/cwd"; }

# Create the state tree; guard the in-repo fallback so it can never be tracked.
hb_ensure_state() {
  local d; d="$(hb_state_dir)"
  mkdir -p "$d/sessions" "$d/cwd" 2>/dev/null
  case "$d" in
    */.claude/sekekama/session-handoff/.state)
      [ -f "$d/.gitignore" ] || printf '*\n' > "$d/.gitignore" 2>/dev/null ;;
  esac
}

# --- Time -------------------------------------------------------------------

hb_timestamp() { date +"%Y-%m-%d-%H%M%S"; }            # sortable filename stamp
hb_iso()       { date +"%Y-%m-%d %H:%M:%S %Z"; }        # human stamp

# Epoch milliseconds (best-effort; falls back to seconds*1000 when %N is absent).
hb_now_ms() {
  local ms; ms="$(date +%s%3N 2>/dev/null)"
  case "$ms" in ''|*[!0-9]*) ms="$(date +%s 2>/dev/null)000" ;; esac
  printf '%s' "$ms"
}

HB_TS_RE='[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}'

# --- Session identity (carried from v1) ------------------------------------

_hb_json_field() {
  printf '%s' "${1:-}" | tr '\n' ' ' \
    | grep -oE "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
    | head -1 | sed -E "s/.*:[[:space:]]*\"([^\"]*)\".*/\1/"
}

# Resolve the session id. $1 (optional) = raw hook stdin payload (JSON).
hb_session_id() {
  local payload="${1:-}" sid="" tp=""
  if [ -n "$payload" ]; then
    if command -v jq >/dev/null 2>&1; then
      sid="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)"
      if [ -z "$sid" ]; then
        tp="$(printf '%s' "$payload" | jq -r '.transcript_path // empty' 2>/dev/null)"
        [ -n "$tp" ] && sid="$(basename "$tp" .jsonl)"
      fi
    fi
    if [ -z "$sid" ]; then
      sid="$(_hb_json_field "$payload" session_id)"
      [ -z "$sid" ] && { tp="$(_hb_json_field "$payload" transcript_path)"; [ -n "$tp" ] && sid="$(basename "$tp" .jsonl)"; }
    fi
  fi
  [ -z "$sid" ] && sid="${CLAUDE_CODE_SESSION_ID:-}"
  [ -z "$sid" ] && sid="nosession"
  printf '%s' "$sid"
}

# Filename-safe short id: up to 12 alphanumerics. Used as THE identity key
# everywhere (filenames, frontmatter session_id, ephemeral state files).
hb_session_short() { hb_session_id "${1:-}" | tr -cd 'a-zA-Z0-9' | cut -c1-12; }
hb_session_is_degraded() { [ "${1:-}" = "nosession" ]; }

# A hook payload's `source` / `reason` / `trigger` (best-effort, jq-optional).
hb_payload_field() {
  local payload="${1:-}" field="${2:-}" v=""
  if command -v jq >/dev/null 2>&1; then
    v="$(printf '%s' "$payload" | jq -r ".${field} // empty" 2>/dev/null)"
  fi
  [ -n "$v" ] || v="$(_hb_json_field "$payload" "$field")"
  printf '%s' "$v"
}

# --- Generic atomic / locked writes ----------------------------------------

# Atomically publish stdin to $1 (temp in same dir, then mv).
hb_atomic_write() {
  local dest="$1" dir tmp
  dir="$(dirname "$dest")"; mkdir -p "$dir" 2>/dev/null
  tmp="$(mktemp "$dir/.hb.XXXXXX" 2>/dev/null)" || { cat > "$dest"; return; }
  cat > "$tmp"
  mv -f "$tmp" "$dest" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; cat > "$dest"; }
}

# Run a command while holding an exclusive lock on $1 (best-effort; no-op if
# flock is unavailable — per-sid/per-cwd keying already removes most contention).
hb_with_lock() {
  local lf="$1"; shift
  mkdir -p "$(dirname "$lf")" 2>/dev/null
  # Group the redirection so a failed open is suppressed WITHOUT permanently
  # redirecting the shell's stderr (a plain `exec 9>f 2>/dev/null` would).
  { exec 9>"$lf"; } 2>/dev/null
  command -v flock >/dev/null 2>&1 && flock -x 9 2>/dev/null
  "$@"; local rc=$?
  exec 9>&- 2>/dev/null
  return $rc
}

# --- Line-oriented key=value state -----------------------------------------

hb_kv_get() {  # file key
  local f="$1" k="$2"
  [ -f "$f" ] || return 0
  sed -nE "s/^${k}=(.*)$/\1/p" "$f" 2>/dev/null | head -1
}

hb_kv_set() {  # file key value   (read-modify-write preserving other keys)
  local f="$1" k="$2" v="$3" dir tmp
  dir="$(dirname "$f")"; mkdir -p "$dir" 2>/dev/null
  tmp="$(mktemp "$dir/.kv.XXXXXX" 2>/dev/null)" || return 1
  { [ -f "$f" ] && grep -vE "^${k}=" "$f" 2>/dev/null; printf '%s=%s\n' "$k" "$v"; } > "$tmp" 2>/dev/null
  mv -f "$tmp" "$f" 2>/dev/null
}

# --- Session→topic map and per-session state -------------------------------

hb_session_topic_file()   { echo "$(hb_sessions_dir)/$1.topic"; }
hb_session_topic_get()    { cat "$(hb_session_topic_file "$1")" 2>/dev/null; }
hb_session_topic_set()    { hb_ensure_state; printf '%s' "$2" | hb_atomic_write "$(hb_session_topic_file "$1")"; }

# Pending cross-topic dependencies (one handoff id per line), consumed by /save.
hb_deps_file()  { echo "$(hb_sessions_dir)/$1.deps"; }
hb_deps_add()   { hb_ensure_state; printf '%s\n' "$2" >> "$(hb_deps_file "$1")" 2>/dev/null; }
hb_deps_read()  { sort -u "$(hb_deps_file "$1")" 2>/dev/null; }
hb_deps_clear() { rm -f "$(hb_deps_file "$1")" 2>/dev/null; }

# Claimed clear-baton: "<cleared_topic>\t<cleared_sid>\t<cleared_at_ms>".
hb_pending_clear_file()  { echo "$(hb_sessions_dir)/$1.pending-clear"; }
hb_pending_clear_set()   { hb_ensure_state; printf '%s\t%s\t%s' "$2" "$3" "$4" | hb_atomic_write "$(hb_pending_clear_file "$1")"; }
hb_pending_clear_topic() { cut -f1 "$(hb_pending_clear_file "$1")" 2>/dev/null; }
hb_pending_clear_clear() { rm -f "$(hb_pending_clear_file "$1")" 2>/dev/null; }

# PreCompact trigger marker (consume-once at SessionStart(compact)).
hb_compact_file()    { echo "$(hb_sessions_dir)/$1.compact"; }
hb_compact_set()     { hb_ensure_state; printf 'trigger=%s\nts=%s\n' "$2" "$3" | hb_atomic_write "$(hb_compact_file "$1")"; }
hb_compact_trigger() { hb_kv_get "$(hb_compact_file "$1")" trigger; }
hb_compact_clear()   { rm -f "$(hb_compact_file "$1")" 2>/dev/null; }

# --- cwd hash, pointer, and clears log -------------------------------------

hb_cwd_hash() {
  local p; p="$(hb_project_dir)"
  if command -v sha1sum >/dev/null 2>&1; then printf '%s' "$p" | sha1sum | cut -c1-16
  elif command -v shasum >/dev/null 2>&1; then printf '%s' "$p" | shasum | cut -c1-16
  else printf '%s' "$p" | tr -c 'a-zA-Z0-9' '-' | cut -c1-40; fi
}

hb_ptr_file()    { echo "$(hb_cwd_dir)/$(hb_cwd_hash).ptr"; }
hb_clears_file() { echo "$(hb_cwd_dir)/$(hb_cwd_hash).clears"; }
hb_cwd_lock()    { echo "$(hb_cwd_dir)/$(hb_cwd_hash).lock"; }

# Pointer: durable "active topic here". Refreshed by /resume and /save only.
hb_ptr_topic() { hb_kv_get "$(hb_ptr_file)" topic; }
_hb_ptr_set() {  # topic sid   (internal; call via hb_ptr_set which locks)
  hb_ensure_state
  local f; f="$(hb_ptr_file)"
  hb_kv_set "$f" topic "$1"
  hb_kv_set "$f" last_sid "$2"
  hb_kv_set "$f" updated_at "$(hb_now_ms)"
}
hb_ptr_set() { hb_with_lock "$(hb_cwd_lock)" _hb_ptr_set "$1" "$2"; }

# Append a /clear event. Fields: ts \t cleared_sid \t cleared_topic \t claimed_by.
_hb_clears_append() {  # cleared_sid cleared_topic
  hb_ensure_state
  printf '%s\t%s\t%s\t-\n' "$(hb_now_ms)" "$1" "${2:-}" >> "$(hb_clears_file)" 2>/dev/null
}
hb_clears_append() { hb_with_lock "$(hb_cwd_lock)" _hb_clears_append "$1" "$2"; }

# Claim a clear-baton for a new (post-/clear) session.
#   $1 = new sid, $2 = freshness window in seconds (default 120).
# Prints on success: "<cleared_topic>\t<cleared_sid>\t<cleared_at_ms>" (the full
#   baton row, so the caller can store a schema-conformant .pending-clear).
#   "AMBIGUOUS" if ≥2 fresh unclaimed; "" if none, or if the consume-once rewrite
#   fails (so the baton stays claimable rather than being double-adopted).
_hb_clears_claim() {
  local nsid="$1" fresh="${2:-120}" f now cutoff lines count ln row topic csid cts tmp
  f="$(hb_clears_file)"; [ -f "$f" ] || { printf ''; return 0; }
  now="$(hb_now_ms)"; cutoff=$(( now - fresh * 1000 ))
  lines="$(awk -F'\t' -v c="$cutoff" '$4=="-" && ($1+0)>=c {print NR}' "$f" 2>/dev/null)"
  count="$(printf '%s\n' "$lines" | grep -c .)"
  if [ "${count:-0}" -eq 0 ]; then printf ''; return 0; fi
  if [ "${count:-0}" -gt 1 ]; then printf 'AMBIGUOUS'; return 0; fi
  ln="$(printf '%s\n' "$lines" | head -1)"
  row="$(awk -F'\t' -v n="$ln" 'NR==n{print}' "$f" 2>/dev/null)"
  cts="$(printf '%s' "$row" | cut -f1)"
  csid="$(printf '%s' "$row" | cut -f2)"
  topic="$(printf '%s' "$row" | cut -f3)"
  # Consume-once: flip claimed_by. Report success ONLY if the rewrite lands —
  # otherwise the entry must remain unclaimed for another session to take.
  tmp="$(mktemp "$(dirname "$f")/.clr.XXXXXX" 2>/dev/null)" || { printf ''; return 0; }
  if awk -F'\t' -v OFS='\t' -v n="$ln" -v s="$nsid" 'NR==n{$4=s} {print}' "$f" > "$tmp" 2>/dev/null \
     && mv -f "$tmp" "$f" 2>/dev/null; then
    printf '%s\t%s\t%s' "$topic" "$csid" "$cts"
  else
    rm -f "$tmp" 2>/dev/null; printf ''
  fi
}
hb_clears_claim() { hb_with_lock "$(hb_cwd_lock)" _hb_clears_claim "$1" "${2:-120}"; }

# --- Handoff filename / id conventions -------------------------------------
#   manual : <ts>-<sid>.md
#   auto   : <ts>-<sid>-auto.md

hb_is_auto()   { printf '%s' "${1:-}" | grep -Eq "^${HB_TS_RE}-[A-Za-z0-9]+-auto\.md$"; }
hb_is_manual() { printf '%s' "${1:-}" | grep -Eq "^${HB_TS_RE}(-[A-Za-z0-9]+)?\.md$" && ! hb_is_auto "${1:-}"; }

# Path for a NEW handoff: mode (manual|auto), sid, topic-slug.
hb_new_handoff_path() {
  local mode="$1" sid="$2" slug="$3" suffix=""
  [ "$mode" = "auto" ] && suffix="-auto"
  echo "$(hb_topic_dir "$slug")/$(hb_timestamp)-${sid}${suffix}.md"
}

# Read a scalar frontmatter field (strips surrounding quotes).
hb_fm_get() {
  local f="$1" k="$2"
  [ -f "$f" ] || return 0
  awk -v key="$k" '
    NR==1 && $0!="---" { exit }
    NR==1 { next }
    $0=="---" { exit }
    {
      if ($0 ~ "^"key":[[:space:]]*") {
        sub("^"key":[[:space:]]*", ""); gsub(/^"|"$/, ""); print; exit
      }
    }
  ' "$f" 2>/dev/null
}

# Canonical handoff id: "<topic>/<ts>-<sid>" (sid-qualified — unique even under
# concurrent same-second saves).
hb_handoff_id() {
  local f="$1" base stem topic
  base="$(basename "$f")"; stem="${base%.md}"; stem="${stem%-auto}"
  topic="$(hb_fm_get "$f" topic)"; [ -n "$topic" ] || topic="$(basename "$(dirname "$f")")"
  printf '%s/%s' "$topic" "$stem"
}

# All handoff files, oldest→newest by their timestamp prefix (across topics).
hb_all_handoffs_bytime() {
  local d; d="$(hb_handoff_dir)"; [ -d "$d" ] || return 0
  find "$d" -type f -name '*.md' 2>/dev/null | while IFS= read -r f; do
    printf '%s\t%s\n' "$(basename "$f")" "$f"
  done | sort | cut -f2-
}

# Newest handoff (auto or manual) authored by session $1. Empty if none.
hb_latest_for_session() {
  local sid="$1" f
  hb_all_handoffs_bytime | while IFS= read -r f; do
    [ "$(hb_fm_get "$f" session_id)" = "$sid" ] && echo "$f"
  done | tail -1
}

# Newest AUTO snapshot authored by session $1. Empty if none.
hb_latest_auto_for_session() {
  local sid="$1" f
  hb_all_handoffs_bytime | while IFS= read -r f; do
    hb_is_auto "$(basename "$f")" && [ "$(hb_fm_get "$f" session_id)" = "$sid" ] && echo "$f"
  done | tail -1
}

# Latest MANUAL handoff in a topic. Empty if none.
hb_latest_manual_in_topic() {
  local slug="$1" d f
  d="$(hb_topic_dir "$slug")"; [ -d "$d" ] || return 0
  ls -1 "$d"/*.md 2>/dev/null | while IFS= read -r f; do
    hb_is_manual "$(basename "$f")" && printf '%s|%s\n' "$(basename "$f")" "$f"
  done | sort | tail -1 | cut -d'|' -f2-
}

# Up to $1 (default 5) most recent topics, newest first: "ts<TAB>topic<TAB>path".
# One row per topic, representative = its newest MANUAL handoff.
hb_recent_topics() {
  local limit="${1:-5}" d f
  d="$(hb_handoff_dir)"; [ -d "$d" ] || return 0
  find "$d" -type f -name '*.md' 2>/dev/null | while IFS= read -r f; do
    hb_is_manual "$(basename "$f")" || continue
    printf '%s\t%s\t%s\n' "$(basename "$f")" "$(hb_fm_get "$f" topic)" "$f"
  done | sort -r | awk -F'\t' 'NF>=2 && !seen[$2]++' | head -n "$limit"
}

# Resolve a "<topic>/<stem>" id or a bare topic slug to a handoff path. A bare
# "<topic>/<timestamp>" alias resolves only when it is UNAMBIGUOUS (spec §5):
# under concurrent same-second saves it would match several sid-tagged files, so
# we return nothing rather than silently pick one (the caller then lists/refuses).
hb_resolve_id() {
  local q="$1" d cand topic stem matches n
  d="$(hb_handoff_dir)"
  case "$q" in
    */*)
      topic="${q%%/*}"; stem="${q#*/}"
      # Exact, sid-qualified id — always unambiguous.
      for cand in "$d/$topic/$stem.md" "$d/$topic/$stem-auto.md"; do
        [ -f "$cand" ] && { echo "$cand"; return 0; }
      done
      # Bare-timestamp alias: accept only on a single match.
      matches="$(ls -1 "$d/$topic/$stem"*.md 2>/dev/null | sort)"
      n="$(printf '%s\n' "$matches" | grep -c .)"
      [ "${n:-0}" -eq 1 ] && printf '%s\n' "$matches" ;;
    *)
      hb_latest_manual_in_topic "$q" ;;
  esac
}

# Reformat a basename's timestamp prefix to "YYYY-MM-DD HH:MM".
hb_handoff_when() {
  printf '%s' "${1:-}" | sed -nE "s/^([0-9]{4}-[0-9]{2}-[0-9]{2})-([0-9]{2})([0-9]{2})[0-9]{2}.*/\1 \2:\3/p"
}

# One-line task summary from a handoff's "## Task & progress" section.
hb_handoff_summary() {
  local f="${1:-}"
  [ -f "$f" ] || return 0
  awk '
    /^##[[:space:]]+Task & progress[[:space:]]*$/ { insec=1; next }
    insec && /^##[[:space:]]/ { exit }
    insec {
      if ($0 ~ /^[[:space:]]*$/) next
      if ($0 ~ /^[[:space:]]*<!--/) next
      if ($0 ~ /^[[:space:]]*#/) next
      print; exit
    }
  ' "$f" 2>/dev/null \
    | sed -E 's/^[[:space:]]*([-*+]|[0-9]+\.)[[:space:]]+//; s/^[[:space:]]*\[[ xX]\][[:space:]]*//; s/\*\*//g; s/^[[:space:]]+//; s/[[:space:]]+$//' \
    | cut -c1-100
}

# --- Slug derivation --------------------------------------------------------

hb_slugify() {
  printf '%s' "${1:-}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' \
    | cut -c1-40 | sed -E 's/-+$//'
}

# Make a NEW topic slug unique against existing, DIFFERENT topic dirs.
hb_unique_topic_slug() {
  local base; base="$(hb_slugify "$1")"
  [ -n "$base" ] || base="topic-$(hb_timestamp)"
  local slug="$base" n=2
  while [ -d "$(hb_topic_dir "$slug")" ]; do
    slug="${base}-${n}"; n=$((n + 1))
  done
  printf '%s' "$slug"
}

# --- Deterministic project facts (carried from v1) -------------------------

hb_git()   { git -C "$(hb_project_dir)" "$@" 2>/dev/null; }
hb_in_git() { hb_git rev-parse --is-inside-work-tree >/dev/null 2>&1; }

hb_detect_commands() {
  local dir found
  dir="$(hb_project_dir)"; found=0
  if [ -f "$dir/package.json" ]; then
    echo "- Node project (\`package.json\`). Scripts:"
    if command -v jq >/dev/null 2>&1; then
      jq -r '.scripts // {} | to_entries[] | "    - `npm run \(.key)`"' "$dir/package.json" 2>/dev/null
    else
      grep -E '"[a-zA-Z0-9:_-]+"[[:space:]]*:' "$dir/package.json" 2>/dev/null | sed 's/^/    /' | head -20
    fi
    found=1
  fi
  if [ -f "$dir/Makefile" ]; then
    echo "- Makefile targets:"
    grep -E '^[a-zA-Z0-9_.-]+:' "$dir/Makefile" 2>/dev/null | sed 's/:.*//' | sed 's/^/    - make /' | head -20
    found=1
  fi
  [ -f "$dir/pyproject.toml" ]   && { echo "- Python project (\`pyproject.toml\`)."; found=1; }
  [ -f "$dir/requirements.txt" ] && { echo "- Python deps: \`pip install -r requirements.txt\`"; found=1; }
  [ -f "$dir/Cargo.toml" ]       && { echo "- Rust: \`cargo build\`, \`cargo test\`."; found=1; }
  [ -f "$dir/go.mod" ]           && { echo "- Go module: \`go build ./...\`, \`go test ./...\`."; found=1; }
  [ -f "$dir/Gemfile" ]          && { echo "- Ruby: \`bundle install\`."; found=1; }
  [ -f "$dir/pom.xml" ]          && { echo "- Maven: \`mvn install\`, \`mvn test\`."; found=1; }
  { [ -f "$dir/build.gradle" ] || [ -f "$dir/build.gradle.kts" ]; } && { echo "- Gradle: \`./gradlew build\`, \`./gradlew test\`."; found=1; }
  { [ -f "$dir/docker-compose.yml" ] || [ -f "$dir/compose.yaml" ]; } && { echo "- Docker Compose present: \`docker compose up\`."; found=1; }
  [ "$found" -eq 0 ] && echo "- _No common build files detected — fill in manually._"
  return 0
}

hb_facts() {
  echo "## Repo snapshot"; echo
  if hb_in_git; then
    local branch; branch="$(hb_git rev-parse --abbrev-ref HEAD)"
    echo "- Branch: \`${branch:-unknown}\`"
    echo "- Working tree:"; echo '```'; hb_git status --short || true; echo '```'
    echo "- Recent commits:"; echo '```'; hb_git log --oneline -5 || true; echo '```'
  else
    echo "- _Not a git repository._"
  fi
  echo; echo "## Environment & commands"; echo
  hb_detect_commands
  return 0
}

# Strip the project-dir prefix for tidy display paths.
hb_rel() { local p="$1" base; base="$(hb_project_dir)/"; echo "${p#"$base"}"; }

# --- Age-based GC sweep -----------------------------------------------------
# Reclaims stale ephemeral state (incl. crash/kill leaks). Throttled to ~1/hr.

hb_gc_sweep() {
  local ttl_days="${1:-14}" sdir cdir sweepdir stamp now last mins cf cutoff tmp
  hb_ensure_state
  sdir="$(hb_sessions_dir)"; cdir="$(hb_cwd_dir)"; sweepdir="$(hb_state_dir)"
  stamp="$sweepdir/.gc.stamp"; now="$(hb_now_ms)"
  last="$(cat "$stamp" 2>/dev/null)"; case "$last" in ''|*[!0-9]*) last=0 ;; esac
  [ $(( now - last )) -lt 3600000 ] && return 0
  printf '%s' "$now" > "$stamp" 2>/dev/null
  mins=$(( ttl_days * 1440 ))
  find "$sdir" -type f -mmin +"$mins" -delete 2>/dev/null
  find "$sweepdir" -maxdepth 1 -type f -name 'enforce.*.count' -mmin +"$mins" -delete 2>/dev/null
  cutoff=$(( now - ttl_days * 86400 * 1000 ))
  for cf in "$cdir"/*.clears; do
    [ -f "$cf" ] || continue
    tmp="$(mktemp "$cdir/.gc.XXXXXX" 2>/dev/null)" || continue
    awk -F'\t' -v c="$cutoff" '($1+0)>=c' "$cf" > "$tmp" 2>/dev/null && mv -f "$tmp" "$cf" 2>/dev/null
  done
  return 0
}

# --- v1 -> v2 migration -----------------------------------------------------
# Idempotent, copy-before-delete (see docs/V2-SPEC.md §9). Brings legacy
# .handoff/*.md handoffs forward into handoffs/legacy/ with synthesized schema-2
# frontmatter. Runs opportunistically (SessionStart + command scripts); the
# .migrated marker + the dir-existence check make repeat calls a cheap no-op.

# "2026-06-07-115525" -> "2026-06-07T11:55:25"  (empty on no match).
_hb_ts_to_iso() {
  printf '%s' "${1:-}" \
    | sed -nE 's/^([0-9]{4}-[0-9]{2}-[0-9]{2})-([0-9]{2})([0-9]{2})([0-9]{2})$/\1T\2:\3:\4/p'
}

hb_migrate_legacy() {
  local legacy marker target f base stem kind ts sid created dest failed any
  legacy="$(hb_legacy_dir)"
  [ -d "$legacy" ] || return 0                 # nothing to migrate (the common case)
  marker="$legacy/.migrated"
  [ -f "$marker" ] && return 0                 # already done

  any=0
  for f in "$legacy"/*.md; do [ -f "$f" ] && { any=1; break; }; done
  [ "$any" -eq 1 ] || return 0                 # dir exists but holds no handoffs

  target="$(hb_topic_dir legacy)"
  mkdir -p "$target" 2>/dev/null || return 0
  failed=0

  for f in "$legacy"/*.md; do
    [ -f "$f" ] || continue
    base="$(basename "$f")"
    # Only timestamp-prefixed handoffs; skips the tombstone README, .migrated, etc.
    printf '%s' "$base" | grep -Eq "^${HB_TS_RE}" || continue
    dest="$target/$base"
    [ -f "$dest" ] && continue                 # idempotent: already copied
    [ -r "$f" ] || { failed=1; continue; }     # unreadable: defer finalizing, retry next run

    kind=manual; hb_is_auto "$base" && kind=auto
    stem="${base%.md}"; stem="${stem%-auto}"
    ts="$(printf '%s' "$stem" | grep -oE "^${HB_TS_RE}")"
    sid="${stem#"$ts"}"; sid="${sid#-}"        # filename tag after the timestamp, if any
    created="$(_hb_ts_to_iso "$ts")"

    if [ "$(head -1 "$f" 2>/dev/null)" = "---" ]; then
      cp "$f" "$dest" 2>/dev/null || failed=1   # already carries frontmatter: copy verbatim
    else
      {
        echo "---"
        echo "schema: 2"
        echo "topic: legacy"
        echo "topic_title: \"Legacy (pre-v2) handoffs\""
        [ -n "$sid" ] && echo "session_id: $sid"
        [ -n "$created" ] && echo "created: $created"
        echo "kind: $kind"
        echo "migrated_from: .handoff/$base"
        echo "---"
        echo
        cat "$f"
      } | hb_atomic_write "$dest" || failed=1
    fi
  done

  # Only finalize once every copy succeeded — a partial run leaves the marker
  # unwritten so the next call retries the stragglers (copy-before-delete: the
  # originals are never touched).
  if [ "$failed" -eq 0 ]; then
    printf 'migrated_at=%s\n' "$(hb_now_ms)" | hb_atomic_write "$marker"
    if [ ! -f "$legacy/README.md" ]; then
      cat > "$legacy/README.md" 2>/dev/null <<EOF
# Migrated to session-handoff v2

These v1 handoffs were copied (not moved) to:

    .claude/sekekama/session-handoff/handoffs/legacy/

with schema-2 frontmatter (topic: legacy). The originals here are kept as a backup
and are no longer read by the plugin. Use /session-handoff:list --any to browse, or
/session-handoff:resume legacy to continue the legacy thread. You may delete this
directory once you've confirmed the migration.
EOF
    fi
  fi
  return 0
}

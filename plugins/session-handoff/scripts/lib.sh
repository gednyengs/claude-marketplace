#!/usr/bin/env bash
# Shared helpers for the session-handoff plugin.
# Sourced by the hook scripts and the slash-command helper scripts.
# Intentionally avoids `set -e` so a single failing git/jq call never aborts a hook.

# Project root. Claude Code exports CLAUDE_PROJECT_DIR to hooks; fall back to cwd.
hb_project_dir() {
  echo "${CLAUDE_PROJECT_DIR:-$(pwd)}"
}

# Directory where handoffs live (version-controlled, travels with the repo).
hb_handoff_dir() {
  echo "$(hb_project_dir)/.handoff"
}

# Sortable filename stamp, e.g. 2026-05-27-143200
hb_timestamp() {
  date +"%Y-%m-%d-%H%M%S"
}

# Human-readable stamp, e.g. 2026-05-27 14:32:00 PDT
hb_iso() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}

# Regex matching the timestamp prefix produced by hb_timestamp (YYYY-MM-DD-HHMMSS).
HB_TS_RE='[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}'

# --- Session identity -------------------------------------------------------
# A handoff belongs to the Claude Code session that produced it. We key
# per-session state on the session id so concurrent sessions in one project
# don't clobber or contaminate each other.

# Extract a top-level JSON string field by name without jq (best-effort, flat objects).
#   $1 = payload, $2 = field name. The hook payload is a flat object whose values
#   here (session_id UUID, transcript path) contain no embedded quotes, so a simple
#   match is safe as a fallback when jq is absent.
_hb_json_field() {
  printf '%s' "${1:-}" | tr '\n' ' ' \
    | grep -oE "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
    | head -1 \
    | sed -E "s/.*:[[:space:]]*\"([^\"]*)\".*/\1/"
}

# Resolve the current session id.
#   $1 (optional): the raw hook stdin payload (JSON). Hooks pass this so we can
#   read the *guaranteed* .session_id field. Slash commands / plain scripts pass
#   nothing and fall back to the environment.
# Priority: stdin .session_id -> stdin transcript_path basename
#           -> $CLAUDE_CODE_SESSION_ID (present but UNDOCUMENTED, best-effort)
#           -> "nosession" (degraded shared bucket).
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
    # No-jq (or jq-miss) fallback: the guaranteed stdin session_id must still win
    # over the undocumented env var, or concurrency safety regresses without jq.
    if [ -z "$sid" ]; then
      sid="$(_hb_json_field "$payload" session_id)"
      if [ -z "$sid" ]; then
        tp="$(_hb_json_field "$payload" transcript_path)"
        [ -n "$tp" ] && sid="$(basename "$tp" .jsonl)"
      fi
    fi
  fi
  [ -z "$sid" ] && sid="${CLAUDE_CODE_SESSION_ID:-}"
  [ -z "$sid" ] && sid="nosession"
  printf '%s' "$sid"
}

# Filename-safe short form of the session id: up to 12 alphanumeric chars.
hb_session_short() {
  hb_session_id "${1:-}" | tr -cd 'a-zA-Z0-9' | cut -c1-12
}

# True when we could not identify the session (degraded shared bucket).
hb_session_is_degraded() {
  [ "${1:-}" = "nosession" ]
}

# --- Handoff filename conventions ------------------------------------------
#   manual : <timestamp>-<sid>.md        (portable / team handoff)
#   auto   : <timestamp>-<sid>-auto.md   (pre-compaction safety snapshot)
# Pre-upgrade files have no <sid> segment; they are treated as portable.

# All handoff files, oldest first (timestamp prefix makes lexical sort chronological).
hb_all_handoffs() {
  local d
  d="$(hb_handoff_dir)"
  [ -d "$d" ] || return 0
  ls -1 "$d"/*.md 2>/dev/null | sort
}

# Is this basename a session-private auto-snapshot? Requires a real sid segment, so
# pre-upgrade `<ts>-auto.md` files (no sid) are NOT treated as private — they fall
# through to the portable/manual bucket and stay visible after upgrading.
hb_is_auto() {
  printf '%s' "${1:-}" | grep -Eq "^${HB_TS_RE}-[A-Za-z0-9]+-auto\.md$"
}

# Is this basename a manual handoff (with or without an embedded sid)?
hb_is_manual() {
  printf '%s' "${1:-}" | grep -Eq "^${HB_TS_RE}(-[A-Za-z0-9]+)?\.md$" && ! hb_is_auto "${1:-}"
}

# Print the session id embedded in a handoff basename, or empty for legacy files.
hb_handoff_sid() {
  local core="${1:-}"
  core="${core%.md}"
  core="${core%-auto}"
  printf '%s' "$core" | sed -E "s/^${HB_TS_RE}//; s/^-//"
}

# Path for a NEW handoff file: mode ($1 = manual|auto), session id ($2).
hb_new_handoff_path() {
  local mode="$1" sid="$2" suffix=""
  [ "$mode" = "auto" ] && suffix="-auto"
  echo "$(hb_handoff_dir)/$(hb_timestamp)-${sid}${suffix}.md"
}

# Newest handoff (auto or manual) belonging to session $1. Empty if none.
hb_latest_for() {
  local sid="$1" f base
  hb_all_handoffs | while IFS= read -r f; do
    base="$(basename "$f")"
    [ "$(hb_handoff_sid "$base")" = "$sid" ] && echo "$f"
  done | tail -1
}

# Newest auto-snapshot belonging to session $1. Empty if none.
hb_latest_auto_for() {
  local sid="$1" f base
  hb_all_handoffs | while IFS= read -r f; do
    base="$(basename "$f")"
    hb_is_auto "$base" && [ "$(hb_handoff_sid "$base")" = "$sid" ] && echo "$f"
  done | tail -1
}

# All MANUAL handoffs across every session (incl. legacy unsuffixed), oldest first.
hb_manual_handoffs() {
  local f base
  hb_all_handoffs | while IFS= read -r f; do
    base="$(basename "$f")"
    hb_is_manual "$base" && echo "$f"
  done
}

# Up to $1 (default 5) most recent MANUAL handoffs, newest first, deduped to the
# latest per session (legacy/untagged files share a single "legacy" bucket).
# Avoids bash-4 associative arrays for portability (macOS ships bash 3.2).
hb_recent_manual() {
  local limit="${1:-5}"
  hb_manual_handoffs | sort -r | {
    seen=" " count=0
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      key="$(hb_handoff_sid "$(basename "$f")")"; key="${key:-legacy}"
      case "$seen" in *" $key "*) continue ;; esac
      seen="$seen$key "
      echo "$f"
      count=$((count + 1))
      [ "$count" -ge "$limit" ] && break
    done
  }
}

# Reformat a handoff basename's timestamp prefix to "YYYY-MM-DD HH:MM". Empty if it
# doesn't match the expected stamp.
hb_handoff_when() {
  printf '%s' "${1:-}" | sed -nE "s/^([0-9]{4}-[0-9]{2}-[0-9]{2})-([0-9]{2})([0-9]{2})[0-9]{2}.*/\1 \2:\3/p"
}

# One-line task summary from a handoff file: the first non-empty, non-comment,
# non-heading line inside the "## Task & progress" section, lightly de-marked and
# capped. Empty if the section is missing/empty (caller falls back to the path).
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

# Atomically publish stdin to $1 (temp file in the same dir, then mv).
hb_atomic_write() {
  local dest="$1" dir tmp
  dir="$(dirname "$dest")"
  mkdir -p "$dir" 2>/dev/null
  tmp="$(mktemp "$dir/.hb.XXXXXX" 2>/dev/null)" || { cat > "$dest"; return; }
  cat > "$tmp"
  mv -f "$tmp" "$dest" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; cat > "$dest"; }
}

# Run git scoped to the project dir, swallowing errors.
hb_git() {
  git -C "$(hb_project_dir)" "$@" 2>/dev/null
}

hb_in_git() {
  hb_git rev-parse --is-inside-work-tree >/dev/null 2>&1
}

# Best-effort detection of how to build/test/run this project.
# Prints markdown bullet lines.
hb_detect_commands() {
  local dir found
  dir="$(hb_project_dir)"
  found=0

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
  [ -f "$dir/pyproject.toml" ]    && { echo "- Python project (\`pyproject.toml\`)."; found=1; }
  [ -f "$dir/requirements.txt" ]  && { echo "- Python deps: \`pip install -r requirements.txt\`"; found=1; }
  [ -f "$dir/Cargo.toml" ]        && { echo "- Rust: \`cargo build\`, \`cargo test\`."; found=1; }
  [ -f "$dir/go.mod" ]            && { echo "- Go module: \`go build ./...\`, \`go test ./...\`."; found=1; }
  [ -f "$dir/Gemfile" ]           && { echo "- Ruby: \`bundle install\`."; found=1; }
  [ -f "$dir/pom.xml" ]           && { echo "- Maven: \`mvn install\`, \`mvn test\`."; found=1; }
  [ -f "$dir/build.gradle" ] || [ -f "$dir/build.gradle.kts" ] && { echo "- Gradle: \`./gradlew build\`, \`./gradlew test\`."; found=1; }
  [ -f "$dir/docker-compose.yml" ] || [ -f "$dir/compose.yaml" ] && { echo "- Docker Compose present: \`docker compose up\`."; found=1; }

  [ "$found" -eq 0 ] && echo "- _No common build files detected — fill in manually._"
  return 0
}

# Deterministic project facts: git state + detected commands. Prints markdown.
hb_facts() {
  echo "## Repo snapshot"
  echo
  if hb_in_git; then
    local branch
    branch="$(hb_git rev-parse --abbrev-ref HEAD)"
    echo "- Branch: \`${branch:-unknown}\`"
    echo "- Working tree:"
    echo '```'
    hb_git status --short || true
    echo '```'
    echo "- Recent commits:"
    echo '```'
    hb_git log --oneline -5 || true
    echo '```'
  else
    echo "- _Not a git repository._"
  fi
  echo
  echo "## Environment & commands"
  echo
  hb_detect_commands
  return 0
}

# Strip the project-dir prefix for tidy display paths.
hb_rel() {
  local p="$1" base
  base="$(hb_project_dir)/"
  echo "${p#"$base"}"
}

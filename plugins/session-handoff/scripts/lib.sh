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

# Path of the most recent handoff file (sorted by timestamped name). Empty if none.
hb_latest_handoff() {
  local d
  d="$(hb_handoff_dir)"
  [ -d "$d" ] || return 0
  ls -1 "$d"/*.md 2>/dev/null | sort | tail -1
}

# Strip the project-dir prefix for tidy display paths.
hb_rel() {
  local p="$1" base
  base="$(hb_project_dir)/"
  echo "${p#"$base"}"
}

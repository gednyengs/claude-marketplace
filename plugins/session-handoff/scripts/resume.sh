#!/usr/bin/env bash
# Prints the most recent handoff in full, for the /session-handoff:resume command.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

latest="$(hb_latest_handoff)"
if [ -z "${latest:-}" ] || [ ! -f "${latest:-}" ]; then
  echo "_No handoff found in $(hb_rel "$(hb_handoff_dir)"). Run /session-handoff:save to create one._"
  exit 0
fi

echo "Source: $(hb_rel "$latest")"
echo
cat "$latest"
exit 0

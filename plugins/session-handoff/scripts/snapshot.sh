#!/usr/bin/env bash
# Prints a deterministic project snapshot (git state + detected commands) as markdown.
# Used by the /session-handoff:save command to give Claude factual ground truth.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

hb_facts
exit 0

#!/usr/bin/env python3
# PreCompact command hook: the one thing this plugin still does from a command
# hook. What it prints is appended by Claude Code to the summarizer's
# instructions, after anything the user typed after /compact.
#
# The hooks module could add the same text by rewriting the compaction's
# instructions, and in 4.0.0's first draft it did. But Claude Code throws away a
# summary it computed ahead of time when a module rewrites the instructions of
# the compaction that installs it, and then summarizes again; text from a
# PreCompact hook is applied to both and costs nothing. So steering stays here,
# and the module only saves the result.
#
# The summary this shapes is saved into the project tree, where it can be
# committed, so the no-secrets rule /session-handoff:save carries applies here too.
import json
import sys

STEERING = (
    "When you write the compaction summary, in addition to anything the user asked you to focus "
    "on above, ensure it preserves — where present — these handoff essentials so work can resume "
    "cleanly in a fresh session: the exact in-flight step quoted verbatim (the edit or command "
    "underway); standing constraints and instructions the user gave, in their own wording; key "
    "decisions and the rationale behind them; questions put to the user that are still unanswered, "
    "with the options offered; open questions and blockers; lessons learned from mistakes or "
    "corrections; any subagents still running, replies still awaited from other agents, and "
    "messages drafted but not yet sent, with what each is for; and the files/functions touched and "
    "why. Never reproduce secrets, tokens, passwords, or credential values in the summary — refer "
    "to them by name or location instead. Do not broaden the scope of an explicitly narrow user "
    "request; within that scope, capture these where they apply.")


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    # A subagent compacting its own transcript is not the conversation the
    # handoff is about, and its summary is not saved.
    if isinstance(payload, dict) and payload.get("agent_id"):
        return
    # As UTF-8 bytes: the text holds characters a non-UTF-8 locale cannot encode,
    # and a failed print here would mean a summary written with no steering at
    # all, silently.
    out = getattr(sys.stdout, "buffer", None)
    if out is not None:
        out.write((STEERING + "\n").encode("utf-8"))
        out.flush()
    else:
        sys.stdout.write(STEERING.encode("ascii", "replace").decode("ascii") + "\n")


if __name__ == "__main__":          # importable for tests; Claude Code runs it as a script
    try:
        main()
    except BaseException:           # a hook must never abort the compaction
        pass
    sys.exit(0)

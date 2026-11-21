#!/usr/bin/env python3
# PreCompact hook. Before the context is compacted, write a *pending* safety
# snapshot (frontmatter + repo snapshot + detected commands) for this session's
# topic, stash the compaction trigger so SessionStart can tell auto from manual,
# and steer Claude Code's own compaction summary toward handoff-relevant content.
#
# The snapshot's BODY is filled in moments later by the PostCompact hook, which
# receives Claude Code's generated compaction summary and persists it here
# (flipping status: pending -> complete). The no-tools summarizer cannot edit
# files during compaction, so we never ask the model to fill the file by hand.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402

# Appended to the compaction summarizer's instructions. The summary this shapes is
# persisted into the project tree by PostCompact, where it can be committed — so
# the no-secrets rule that /save has always carried applies here too.
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


def body():
    payload = sys.stdin.read()
    ok, _rest = lib.bootstrap(sys.argv[1:], strict=False)
    if not ok:
        return
    sid = lib.session_short(payload)
    trigger = lib.payload_field(payload, "trigger") or "auto"
    degraded = lib.session_is_degraded(sid)

    # Resolve this session's topic; lazily create a provisional one if it has none.
    # A degraded session has no usable identity, so it neither reads nor writes the
    # shared "nosession" binding — otherwise two unidentified sessions would adopt
    # each other's topic. It still gets a snapshot, just under its own fresh topic.
    slug = "" if degraded else lib.safe_slug(lib.session_topic_get(sid))
    if not slug:
        slug = lib.unique_topic_slug("topic-" + lib.timestamp())
        if not degraded:
            lib.session_topic_set(sid, slug)

    # Best-effort human title (carried from an earlier handoff in this topic).
    title = slug
    latest = lib.latest_ready_in_topic(slug)
    if latest:
        t = lib.fm_get(latest, "topic_title")
        if t:
            title = t

    # A degraded run has no identity PostCompact could use to find this exact file
    # again — every degraded session resolves to the same "nosession" key, so
    # "complete the pending skeleton" would let one such session finish (or adopt)
    # another's. Publish it finished instead: PostCompact writes its summary to a
    # separate file rather than reaching for a skeleton that may not be its own.
    if degraded:
        status = "complete"
        note = ["> Auto-snapshot taken before context compaction (trigger: %s)." % trigger,
                "> This session had no usable session id, so the compaction summary is saved",
                "> as a separate handoff rather than being merged into this file."]
    else:
        status = "pending"
        note = ["> Auto-snapshot taken before context compaction (trigger: %s)." % trigger,
                "> Claude Code's compaction summary is persisted into this file once compaction",
                "> completes; until then this is a repo-state safety record."]

    f = lib.new_handoff_path("auto", sid, slug)
    facts = lib.facts()     # before the digest below, which may use up the git time budget
    content = "\n".join([
        "---",
        "schema: 2",
        "topic: " + slug,
        "topic_title: " + lib.fm_quote(title),
        "session_id: " + sid,
        "created: " + lib.created_stamp(),
        "kind: auto",
        "status: " + status,
        "compact_trigger: " + trigger,
    ] + lib.git_fm_lines() + [
        "---",
        "",
        "# Handoff — " + lib.iso(),
        "",
    ] + note + [
        "",
        facts,
    ])
    if lib.atomic_write(f, content + "\n") and status == "complete":
        lib.receipt_add(f)          # a degraded snapshot is published finished

    # Stash the trigger so SessionStart(source=compact) can tell auto from manual.
    lib.compact_set(sid, trigger, lib.now_ms())

    # Steer Claude Code's compaction summary. Our stdout is appended to the
    # summarizer's instructions AFTER any /compact text the user supplied
    # (Claude Code concatenates them) — additive, never exclusive — so we phrase
    # it to defer to a deliberately narrow user request.
    print(STEERING)

if __name__ == "__main__":          # importable for tests; hooks run it as a script
    lib.run_hook(body)

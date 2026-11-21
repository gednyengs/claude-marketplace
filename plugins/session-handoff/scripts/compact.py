#!/usr/bin/env python3
# Compaction snapshot. The hooks module (hooks/register.ts) runs this once Claude
# Code has compacted the main conversation, passing on stdin what it collected:
#
#   session_id       the session that was compacted
#   trigger          manual | auto | plugin
#   compact_summary  the summary as Claude Code's PostCompact event carries it
#   agents           the agents Claude Code lists as running
#
# It writes ONE complete handoff holding that summary, so the narrative survives
# /clear and restarts (Claude Code's in-context copy does not), and prints a line
# saying where it went, which the module shows in the transcript under the
# plugin's name.
#
# Before 4.0.0 this took two hook processes: PreCompact wrote a pending skeleton
# and PostCompact found it again and filled it in. The module wraps the whole
# compaction in one hook, so there is no skeleton to find, no trigger to stash
# between processes, and nothing left behind when a compaction is aborted.
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402

WRAP_HEADER = "## Compaction summary (auto-generated)"
AGENTS_HEADER = "## Agents running at compaction"


def clean_summary(s):
    """Extract the handoff content from Claude Code's compaction summary.

    Claude Code emits the summary wrapped as
        <analysis>...chain-of-thought...</analysis>
        <summary>...the 9-section handoff...</summary>
    We persist only the <summary> body; the <analysis> block is meta-reasoning.

    Resolution, robust to format drift and truncation:
      1. Strip only a *leading* <analysis>...</analysis> wrapper — anchored at the
         start, where Claude Code always emits it — so a stray '<summary>' quoted
         inside that wrapper can't fool the extractor, while a closed
         '<analysis>...</analysis>' pair the summary *itself* quotes is left intact.
         Then return the <summary> body, matching from the first '<summary>' opener
         to the *last* '</summary>' closer (greedy) so a literal '<summary>...
         </summary>' pair quoted inside the body is preserved — Claude Code emits a
         single outer wrapper. Extraction is unanchored, so it still works if a
         future version prepends a preamble before <analysis>.
      2. No usable <summary>: if what remains begins with an unclosed '<analysis'
         (chain-of-thought truncated before any summary), persist nothing — return
         "" rather than store raw chain-of-thought.
      3. Otherwise treat the remainder as an un-tagged summary (a future/un-wrapped
         format) and return it, with any dangling <summary> tags stripped.
    """
    s = s or ""
    body = re.sub(r"^\s*<analysis\b.*?</analysis>\s*", "", s, flags=re.S | re.I)
    m = re.search(r"<summary>(.*)</summary>", body, re.S | re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()
    rest = body.strip()
    if re.match(r"<\s*analysis\b", rest, re.I):
        return ""
    return re.sub(r"</?summary>", "", rest, flags=re.I).strip()


def compose(fm_lines, summary, trigger, facts=None, agents=None):
    body = [
        "# Handoff — " + lib.iso(),
        "",
        WRAP_HEADER,
        "",
        "> Persisted from Claude Code's compaction summary (trigger: %s) so it survives /clear "
        "and restarts." % trigger,
        "",
        summary.strip(),
        "",
    ]
    if agents:
        body += [
            AGENTS_HEADER,
            "",
            "> Listed by Claude Code when this snapshot was taken, not recalled by the model. "
            "Whether each is still running depends on how the next session starts.",
            "",
        ] + lib.agents_lines(agents) + [""]
    body.append(lib.facts() if facts is None else facts)
    return "\n".join(fm_lines + [""] + body) + "\n"


def _field(data, key):
    v = data.get(key)
    return v if isinstance(v, str) else ""


def body():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    ok, _rest = lib.bootstrap(sys.argv[1:], strict=False)
    if not ok:
        return
    sid = lib.short_id(_field(data, "session_id")) or lib.session_short()
    degraded = lib.session_is_degraded(sid)
    trigger = lib.sanitize_line(_field(data, "trigger"), 20)
    if trigger not in ("manual", "auto", "plugin"):
        trigger = "auto"

    # Only the PostCompact form is saved: it is the summary alone, and
    # clean_summary() knows how to keep chain-of-thought out of it. The message the
    # conversation holds afterwards wraps the summary in Claude Code's continuation
    # text (a transcript path under the user's home, an instruction to carry on
    # without asking) and is never used as a stand-in.
    summary = clean_summary(_field(data, "compact_summary"))
    if not summary:
        # Nothing worth a file: a snapshot with no narrative would become the
        # topic's newest handoff and hide a better one from resume.
        print("Context was compacted, but Claude Code provided no usable summary, "
              "so no snapshot was saved. Run /session-handoff:save to capture task state.")
        return

    # A session with no usable id never reads or writes the shared "nosession"
    # binding — two such sessions would adopt each other's topic. It still gets
    # a snapshot, under a topic of its own.
    slug = "" if degraded else lib.safe_slug(lib.session_topic_get(sid))
    if not slug:
        slug = lib.unique_topic_slug("topic-" + lib.timestamp())
        if not degraded:
            lib.session_topic_set(sid, slug)
    title = slug
    latest = lib.latest_ready_in_topic(slug)
    if latest:
        t = lib.fm_get(latest, "topic_title")
        if t:
            title = t

    target = lib.new_handoff_path("auto", sid, slug)
    facts = lib.facts()     # before the digest below, which may use up the git time budget
    fm = [
        "---",
        "schema: 2",
        "topic: " + slug,
        "topic_title: " + lib.fm_quote(title),
        "session_id: " + sid,
        "created: " + lib.created_stamp(),
        "kind: auto",
        "status: complete",
        "compact_trigger: " + trigger,
    ] + lib.git_fm_lines() + [          # the state the repo snapshot below describes
        "---",
    ]
    agents = lib.agents_clean(data.get("agents"))
    if lib.atomic_write(target, compose(fm, summary, trigger, facts, agents)):
        lib.receipt_add(target)
        print("Compaction summary saved to %s." % lib.rel(target))


if __name__ == "__main__":          # importable for tests; the module runs it as a script
    lib.run_hook(body)

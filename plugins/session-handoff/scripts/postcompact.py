#!/usr/bin/env python3
# PostCompact hook. Claude Code has just produced its compaction summary and
# passes it to us as `compact_summary`. We persist that summary as the durable
# handoff body so it survives /clear (Claude Code's in-context copy does not).
#
# Normal path: complete the *pending* safety snapshot PreCompact just wrote
# (flip status: pending -> complete and fill the body). Reactive prompt-too-long
# compaction skips PreCompact, so when no pending snapshot exists we create a
# completed handoff from scratch. We find the skeleton by recency rather than a
# stashed path because SessionStart(source=compact) — which runs *before* us —
# has already cleared the compaction stash.
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402

WRAP_HEADER = "## Compaction summary (auto-generated)"


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
         "" so body() keeps the pending skeleton rather than store raw CoT.
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


def compose(fm_lines, summary, trigger, facts=None):
    summary = (summary or "").strip()
    if summary:
        note = ("> Persisted from Claude Code's compaction summary "
                "(trigger: %s) so it survives /clear and restarts." % trigger)
        content = summary
    else:
        # No usable summary, but PreCompact already wrote (and SessionStart already
        # announced) this file. Complete it with an explicit statement of what is
        # missing rather than leaving a `pending` file that discovery hides — a
        # handoff the user was told exists must be findable, even if degraded.
        note = ("> Compaction ran (trigger: %s), but Claude Code did not provide a usable "
                "summary." % trigger)
        content = ("_The conversation narrative for this compaction could not be preserved._\n\n"
                   "_The repo snapshot below is still accurate as of the moment compaction began. "
                   "Use `/session-handoff:save` to capture the task state by hand._")
    body = [
        "# Handoff — " + lib.iso(),
        "",
        WRAP_HEADER,
        "",
        note,
        "",
        content,
        "",
        lib.facts() if facts is None else facts,
    ]
    return "\n".join(fm_lines + [""] + body) + "\n"


def body():
    payload = sys.stdin.read()
    ok, _rest = lib.bootstrap(sys.argv[1:], strict=False)
    if not ok:
        return
    sid = lib.session_short(payload)
    degraded = lib.session_is_degraded(sid)
    trigger = lib.payload_field(payload, "trigger") or "auto"
    summary = clean_summary(lib.payload_field(payload, "compact_summary"))

    # Prefer to complete the pending skeleton PreCompact just wrote (seconds ago).
    # The freshness guard avoids filling a STALE pending skeleton left by an earlier
    # aborted compaction: in that case (e.g. a later reactive compaction, which skips
    # PreCompact) we want a fresh handoff, not this summary backdated onto the old file.
    # Skeleton adoption is keyed on the session id, so it is only safe when we
    # actually have one: every degraded run shares "nosession", and adopting by
    # recency there could complete a DIFFERENT degraded session's snapshot. A
    # degraded run therefore always writes its own new file (PreCompact already
    # published its snapshot as complete for the same reason).
    target = "" if degraded else lib.latest_auto_for_session(sid)
    fresh_pending = False
    if target and lib.is_pending(target):
        try:
            fresh_pending = (time.time() - os.path.getmtime(target)) < 1800  # 30 min
        except OSError:
            fresh_pending = False

    # Nothing to say AND nothing already promised: stay out of the way entirely.
    # With a fresh skeleton we always finish the file — see compose().
    if not summary.strip() and not fresh_pending:
        return

    if fresh_pending:
        snap = lib.fm_all(target)
        slug = lib.fm_topic(target, snap)
        if not slug:
            return                      # skeleton in an unusable location
        title = snap.get("topic_title") or slug
        created = snap.get("created") or lib.created_stamp()
    else:
        # Reactive / no skeleton: create a fresh completed handoff. As in PreCompact,
        # a degraded session never touches the shared "nosession" topic binding.
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
        created = lib.created_stamp()
        target = lib.new_handoff_path("auto", sid, slug)

    facts = lib.facts()     # before the digest below, which may use up the git time budget
    fm = [
        "---",
        "schema: 2",
        "topic: " + slug,
        "topic_title: " + lib.fm_quote(title),
        "session_id: " + sid,
        "created: " + created,
        "kind: auto",
        "status: complete",
        "compact_trigger: " + trigger,
    ] + lib.git_fm_lines() + [          # the state the repo snapshot below describes
        "---",
    ]
    if lib.atomic_write(target, compose(fm, summary, trigger, facts)):
        lib.receipt_add(target)
        if summary.strip():
            print("[session-handoff] Compaction summary persisted to %s." % lib.rel(target))
        else:
            print("[session-handoff] No usable compaction summary was provided; %s holds the repo "
                  "snapshot only. Run /session-handoff:save to capture task state."
                  % lib.rel(target))

if __name__ == "__main__":          # importable for tests; hooks run it as a script
    lib.run_hook(body)

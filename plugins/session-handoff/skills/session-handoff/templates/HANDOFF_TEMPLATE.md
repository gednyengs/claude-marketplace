<!--
Frontmatter is the source of truth (topic, provenance, cross-topic links). Use the exact
block printed by new-path.py; the fields below show the schema. `note` and `depends_on` are
optional — omit them when empty.
-->
---
schema: 2
topic: <topic-slug>                       # stable kebab-case slug; the unit of continuity
topic_title: "<Human-readable title>"     # may be refined later without renaming the slug
session_id: <sid>                         # originating session (provenance + collision-avoidance)
created: <YYYY-MM-DDThh:mm:ss±zz:zz>
kind: manual                              # manual | auto
note: "<optional one-line label the writer may add; not the /save note, which is folded into the body>"
depends_on:                               # optional; cross-topic handoff ids only
  - <other-topic>/<timestamp>-<sid>
---

# Handoff — <YYYY-MM-DD HH:MM:SS TZ>

## Task & progress

<!--
The goal in one or two sentences, then:
- Done: …
- In progress: …
- Not started: …
-->

## Key decisions & rationale

<!--
The choices that matter and *why*, so they aren't relitigated next session.
- Decision — rationale
-->

## Approaches tried & dead ends

<!--
OPTIONAL. Include this section only when you hit attempts that would be expensive or tempting for the
next session to repeat: list what was tried and why it failed or was abandoned. Omit the whole section
(heading included) when there were no such dead ends.
- Tried X -> failed because Y
-->

## Open questions & blockers

<!--
Unresolved questions, things waiting on input, and known risks.
- …
-->

## Next steps

<!--
An ordered, actionable checklist. The first item should be unambiguous.
1. …
2. …
-->

## Environment, commands & results

<!--
How to build / test / run, required env vars, and setup. Start from the auto-detected commands and
refine with what you actually ran this session. Also record meaningful pass/fail results or
measurements, and the paths to any data files or artifacts the next session needs (JSON, CSV, logs).
-->

## Repo snapshot

<!--
Branch, working-tree status, and recent commits (from snapshot.py).
-->

## Resume instructions

<!--
The first concrete actions the next session should take to get oriented and continue.
-->

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

## Environment & commands

<!--
How to build / test / run, required env vars, setup steps, and how to reproduce the
current working state. Start from the auto-detected commands and refine.
-->

## Repo snapshot

<!--
Branch, working-tree status, and recent commits (from snapshot.py).
-->

## Resume instructions

<!--
The first concrete actions the next session should take to get oriented and continue.
-->

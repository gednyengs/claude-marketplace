---
name: to-prd
description: Synthesize a PRD from a GRILL decision record and save it under .claude/specs/<feature>/. Use when the user wants to create a PRD from a grilling session.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

This skill turns a GRILL decision record into a PRD. It does NOT interview the user and never invents a decision — it synthesizes only what the GRILL (and codebase) already establish.

## Artifact rules (shared across grill-me / to-prd / to-plan)

Artifacts live at `.claude/specs/<feature_slug>/<TYPE>-<YYYY-MM-DD-HHMMSS>.md` (`TYPE` ∈ GRILL, PRD, PLAN) and are append-only — never overwrite a file's body. Every artifact carries this frontmatter:

```
feature_id:   F-<feature_slug>      # set once at feature creation; reused UNCHANGED by every later artifact and revision
feature_slug: <kebab-case slug>
artifact_id:  <this file's name without ".md", e.g. PRD-2026-06-01-143500>
type:         grill | prd | plan
status:       draft | ready | superseded
blocking_open_items: <integer = count of blocking items in this file's Open Items / Missing Decisions>
source:       []                     # artifact_id(s) this was derived from (GRILL for a PRD, PRD for a PLAN)
supersedes:   []                     # artifact_id(s) this explicitly replaces
stale:        false
created:      <YYYY-MM-DD-HHMMSS>     # identical to the timestamp in the filename
```

Emit **every** field above in every artifact, in this order; use `[]` or `false` where a field doesn't apply.

Apply these definitions exactly:
- **Timestamps** come from the real wall clock — run `date +%Y-%m-%d-%H%M%S`. `artifact_id` = filename without `.md`; `created` = the same timestamp.
- **Resolve `<feature>`** by exact folder-name match under `.claude/specs/` only. No exact match → list candidates and stop. Multiple partial matches → stop and ask. Never guess.
- **Latest** artifact of a type = highest `created` among those whose `status` ≠ `superseded`. Tie → lexicographically greatest filename. Still ambiguous → stop and ask the user to name it.
- **`stale: true` ⇒ the artifact cannot be `ready`.** An artifact is stale when its `source` is not the latest non-superseded artifact (of the source's type) for the feature.
- Only the artifact currently being written may be `draft` or `ready`; an older artifact may be set `superseded` only when explicitly replaced.

---

**Source.** Resolve the feature folder (per the Artifact rules) and read its GRILL — the latest non-superseded `GRILL-*.md` unless the user names one. The live conversation may only help you *locate* the right GRILL; do not carry any decision, requirement, invariant, or assumption into the PRD unless it is in the GRILL or directly verified from the repo.

**Fail closed (machine-checkable).** Set the PRD `status: ready` only if the source GRILL is `status: ready` AND is the latest non-superseded GRILL for the feature. Otherwise write `status: draft`: if the GRILL has blocking Open items, add a **Missing Decisions** section listing them (never fabricate them); if the GRILL is not the latest, also set `stale: true` and warn the user loudly, naming both GRILLs. A PRD is never both `ready` and `stale`.

## Process

1. Explore the repo if you haven't already. Use the project's domain glossary throughout; respect any ADRs in the area you're touching; flag a decision worth a new ADR only if the project already uses ADRs.

2. Synthesize the template below. Assign stable IDs: requirements `R##`, invariants `I##`. For exact formal contracts, **do not restate them in prose — reference the GRILL contract by ID** (e.g. "Grammar: see GRILL `C03`"). Keep the PRD a clean behavioral summary; the GRILL holds the authoritative detail.

3. Confirm the testing seams from the GRILL's context block — do not ask the user. If seams were never resolved, treat that as a blocking Missing Decision (fail closed).

4. Write to `.claude/specs/<feature>/PRD-<timestamp>.md` per the Artifact rules (`type: prd`, `source: [<GRILL artifact_id>]`). `blocking_open_items` = the count of items in the Missing Decisions section. Then report the path and the resulting status.

<prd-template>

## Problem Statement

The problem being solved, from the perspective of whoever — or whatever — consumes this: a person, a calling subsystem, another process.

## Solution

The solution to that problem, from the consumer's perspective.

## Requirements

The behavior the feature must exhibit, as a complete numbered list (`R01`, `R02`, …) that covers every aspect. Where there is a real actor, write user stories:

R01. As an <actor>, I want a <capability>, so that <benefit>

The actor need not be human — it may be a calling subsystem, a userspace process, a device, a downstream stage, or a library consumer. For internal mechanism with no meaningful actor, state the requirement as a behavioral contract instead:

R0N. Given <context>, when <event or call>, the component must <guarantee>.

Cover all observable behavior, but do not pad into fake prose.

## Invariants & Contracts

Properties that must always hold, listed `I01`, `I02`, …. For exact formal contracts (grammars, schemas, IR, type rules, wire/diagnostic formats), reference the GRILL contract IDs (`C##`) rather than restating them — the GRILL is authoritative.

## Implementation Decisions

The decisions made, drawn from the GRILL (cite `D##`/`C##` where useful): modules built/modified, interfaces changed, architectural decisions, schema changes, API contracts, specific interactions. Do NOT include exact file paths or code snippets — component and module names are fine when they clarify scope.

## Failure & Recovery

How the feature behaves when things go wrong: anticipated failures, how they propagate, the recovery or fallback, and which invariants must still hold on the failure path.

## Conformance

If the work must conform to a governing specification (a standard, a published contract, an external format), name it and record intended deviations. Omit if none applies.

## Testing Decisions

What makes a good test (test external behavior, not implementation details); the seams the feature is tested at (from the GRILL); which modules will be tested; verification methods appropriate to the work; prior art for the tests in the codebase.

## Assumptions

Decisions that were assumed rather than confirmed, taken from the GRILL, each flagged `blocking: true|false`. An implementing agent should treat these as the items most likely to be wrong.

## Out of Scope

What this PRD explicitly does not cover.

## Missing Decisions

Only present when `status: draft`. The blocking Open items from the GRILL that must be resolved before this PRD is ready for an agent.

## Further Notes

Non-normative context only. No requirement, invariant, contract, or implementation decision may appear *only* here — those belong in their own sections.

</prd-template>

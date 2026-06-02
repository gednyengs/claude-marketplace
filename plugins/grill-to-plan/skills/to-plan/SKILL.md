---
name: to-plan
description: Turn a PRD into a dependency-ordered implementation PLAN (Plan architect drafts it, a bounded Codex review hardens it) and save it under .claude/specs/<feature>/. Use when the user wants an implementation plan from a PRD.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent(Plan), Skill
---

This skill turns a PRD into an implementation **PLAN** — the basis for creating implementation tasks. A read-only Plan architect subagent drafts it; a bounded Codex review loop hardens it. It does NOT interview the user.

## Artifact rules (shared across grill-me / to-prd / to-plan)

Artifacts live at `.claude/specs/<feature_slug>/<TYPE>-<YYYY-MM-DD-HHMMSS>.md` (`TYPE` ∈ GRILL, PRD, PLAN) and are append-only — never overwrite a file's body. Every artifact carries this frontmatter:

```
feature_id:   F-<feature_slug>      # set once at feature creation; reused UNCHANGED by every later artifact and revision
feature_slug: <kebab-case slug>
artifact_id:  <this file's name without ".md", e.g. PLAN-2026-06-01-144020>
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

**Source & gate (machine-checkable, whole chain).** Resolve the feature folder and read its latest non-superseded `PRD-*.md` (or the one the user names) and that PRD's source GRILL. Plan only if ALL hold: PRD `status: ready`; PRD `stale: false`; the source GRILL exists, is `status: ready`, not superseded, and is the latest GRILL for the feature. **If any check fails, stop before planning and report the specific blocker — do not write a PLAN.** Never invent a missing decision.

## Process

1. **Build the input bundle.** Assemble: the full PRD; the GRILL contract/decision sections (`C##`/`D##`) the PRD references; the PRD's Assumptions and (if any) Missing Decisions; and the list of all requirement/invariant/contract IDs (`R##`/`I##`/`C##`). Every blocking item must either map to the tasks it blocks or prevent a `ready` PLAN. This bundle — not the live conversation — is the planning input.

2. **Generate via the Plan architect.** Spawn the `Plan` subagent (read-only architect that explores the repo) with the input bundle. Require it to return:
   - component decomposition and a dependency DAG;
   - build order as **vertical-slice milestones** — the first milestone must exercise the full externally-meaningful path for the smallest valid input;
   - ordered tasks `T##`, each with: scope, depends-on, acceptance criteria that **cite the source IDs** they satisfy (`R##`/`I##`/`C##`), test seam & method, rough size, and risks;
   - cross-cutting workstreams (e.g. diagnostics, error handling, test harness, build/toolchain) as the work demands;
   - open risks.

   **Ban invented contracts:** any formal rule the plan relies on must cite a GRILL/PRD ID. If it isn't in the sources, the plan records it as an open risk — never as a task basis.

3. **Review loop with Codex (max 2 rounds).** Send the draft PLAN plus the full input bundle from step 1 (including the GRILL `C##` contracts) to Codex via the `codex-runner` skill with this rubric:
   - (a) **coverage** — every `R##`/`I##`/`C##` maps to ≥1 task;
   - (b) **ordering** — no task depends on later work; prerequisites present;
   - (c) **granularity** — each task is independently implementable and testable;
   - (d) **missing cross-cutting work**;
   - (e) the first milestone is a true end-to-end vertical slice.

   Require Codex to classify each finding `blocking | non-blocking | style`. Only `blocking` findings trigger a revision and another round. Stop at the first clean round; **cap at 2 rounds**. If blocking findings remain after 2 rounds, write the plan `status: draft` with a review caveat and surface that the PRD/GRILL inputs are likely underspecified. If `codex-runner` is unavailable, stop and report that the PLAN could not be reviewed — do not mark it `ready`.

4. **Write the PLAN.** Save to `.claude/specs/<feature>/PLAN-<timestamp>.md` per the Artifact rules (`type: plan`, `source: [<PRD artifact_id>]`), plus `review: passed | with-caveats`. `blocking_open_items` = the count of unresolved blocking items carried into the plan. Then report the path, the status, and the review outcome.

<plan-template>

## Overview

Goal and scope, from the PRD.

## Architecture & Components

The components and their dependency DAG, including the inter-component contracts (cite `C##`).

## Build Order & Milestones

The vertical slices, in order. The first slice must exercise the full externally-meaningful path for the smallest valid input.

## Tasks

Ordered tasks. Each `T##`:
- **Scope** — what it builds/changes (component/module level, no file paths).
- **Depends-on** — the task IDs that must precede it.
- **Acceptance criteria** — citing the `R##`/`I##`/`C##` they satisfy.
- **Test** — the seam and method.
- **Size** — rough estimate.
- **Risks.**

## Cross-cutting Workstreams

Work that spans tasks (e.g. diagnostics, error handling, test harness, build/toolchain), as the work demands.

## Traceability

A table mapping every `R##`/`I##`/`C##` to the task(s) that satisfy it. This is the coverage guarantee — every requirement, invariant, and contract must appear.

## Risks & Assumptions

Open risks and assumptions carried into implementation.

## Review Summary

The blocking Codex findings and how each was resolved.

</plan-template>

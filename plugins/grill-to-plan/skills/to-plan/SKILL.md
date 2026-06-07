---
name: to-plan
description: Turn a PRD into a dependency-ordered implementation PLAN (Plan architect drafts it, a bounded independent review hardens it — an in-model subagent by default, or an external cross-model Codex review with the user's consent) and save it under .claude/specs/<feature>/. Use when the user wants an implementation plan from a PRD.
allowed-tools: AskUserQuestion, Read, Write, Edit, Bash, Glob, Grep, Agent(Plan), Agent(general-purpose), Skill
---

This skill turns a PRD into an implementation **PLAN** — the basis for creating implementation tasks. A read-only Plan architect subagent drafts it; a bounded independent review loop hardens it — an in-model subagent by default, or an external cross-model Codex review (via the `codex-runner` skill) when the user opts in. It does not interview the user about the design; it may ask once which reviewer to use.

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
- **Provenance** — every surface, decision, and formal contract in the GRILL is tagged `code-confirmed`, `spec-derived`, `design-intended`, or `assumed`. A task whose acceptance rests on an `assumed`-provenance source inherits that risk; surface it under the task's risks.
- Only the artifact currently being written may be `draft` or `ready`; an older artifact may be set `superseded` only when explicitly replaced.

---

**Source & gate (machine-checkable, whole chain).** Resolve the feature folder and read its latest non-superseded `PRD-*.md` (or the one the user names) and that PRD's source GRILL. Plan only if ALL hold: PRD `status: ready`; PRD `stale: false`; the source GRILL exists, is `status: ready`, not superseded, and is the latest GRILL for the feature. **If any check fails, stop before planning and report the specific blocker — do not write a PLAN.** Never invent a missing decision.

## Process

1. **Build the input bundle.** Assemble: the full PRD; the GRILL contract/decision sections (`C##`/`D##`) the PRD references; the GRILL **Surface Inventory** (`S##`, with provenance); the PRD's Assumptions and (if any) Missing Decisions; and the list of all requirement/invariant/contract/surface IDs (`R##`/`I##`/`C##`/`S##`). Every blocking item must either map to the tasks it blocks or prevent a `ready` PLAN. This bundle — not the live conversation — is the planning input.

2. **Generate via the Plan architect.** Spawn the `Plan` subagent (read-only architect that explores the repo) with the input bundle. Require it to return:
   - component decomposition and a dependency DAG;
   - build order as **vertical-slice milestones** — the first milestone must exercise the full externally-meaningful path for the smallest valid input;
   - ordered tasks `T##`, each with: scope, depends-on, acceptance criteria that **cite the source IDs** they satisfy (`R##`/`I##`/`C##`, and the `S##` surface they realize where one applies), test seam & method, rough size, and risks;
   - coverage of every GRILL surface (`S##`): each one marked covered by a `D##`/`C##` maps to ≥1 task or is explicitly recorded out of scope; negative-space surfaces (`considered — no decision`/`considered — N/A`) are carried as-is, never turned into tasks;
   - cross-cutting workstreams (e.g. diagnostics, error handling, test harness, build/toolchain) as the work demands;
   - open risks.

   **Ban invented contracts:** any formal rule the plan relies on must cite a GRILL/PRD ID. If it isn't in the sources, the plan records it as an open risk — never as a task basis.

3. **Independent review loop (max 2 rounds).** Have a **separate reviewer** critique the draft PLAN against the full input bundle from step 1 (including the GRILL `C##` contracts).

   **Choose the reviewer — with consent for external review.** Two reviewers are possible: **Codex**, an external cross-model reviewer via the `codex-runner` skill, and an **in-model subagent**, a `general-purpose` subagent in the same model family as the `Plan` drafter. Codex gives genuinely independent (cross-model) critique, but invoking it **sends the PRD, the GRILL contracts, and the draft PLAN to an external service and incurs cost** — so it runs **only on explicit consent**, and the in-model subagent is always the safe default.

   **Explicit consent** means exactly one of: the user picked Codex in answer to the consent prompt below; the user requested Codex in the current invocation (e.g. "review with codex"); or a documented, Codex-specific standing preference for this skill authorizes it. **Never infer consent** from prior chat, stale memory, project notes, vague phrasing, or the mere fact that `codex-runner` is installed.

   Decide as follows:
   - If explicit consent (as defined) is already on record for this run → use the reviewer it names; do not prompt.
   - Otherwise, **only if** the `codex-runner` skill is present **and** the session is confirmed interactive → ask **once** with `AskUserQuestion` (not per round): **Codex** (external cross-model review — content leaves the environment, costs) vs **in-model subagent** (local, same-model, no egress). Use Codex only if the user picks it here.
   - Otherwise → **default to the in-model subagent.** This branch covers every uncertain case: `codex-runner` absent; the session non-interactive/headless; interactivity that cannot be confirmed (treat as non-interactive); or `AskUserQuestion` being unavailable, erroring, timing out, or dismissed/unanswered. **Never default to Codex.**

   **Lock the choice for the whole loop.** Select the reviewer once, before the loop begins, and reuse it for both rounds. Never switch reviewers mid-loop — in particular, never escalate to Codex in round 2 without prior explicit consent. (This is a one-time reviewer-consent prompt, not part of PRD/design elicitation.)

   **Run the chosen reviewer:**
   - **Codex (only if explicitly chosen):** **attempt** the review through `codex-runner`. Treat it as having run only when the invocation succeeds within its timeout — do not gate on a preflight like `codex --version`. If it is absent, exits non-zero, times out, or otherwise fails, **fall back to the in-model subagent** and note the fallback. The subagent never escalates back to Codex.
   - **In-model subagent:** spawn a `general-purpose` subagent (**not** the `Plan` architect) with the same bundle. Brief it explicitly to be read-only — **critique only; do not edit files or write artifacts** (step 4 owns the write). This is a same-model review: independent in context and role, but not in model, so weaker independence than Codex.

   The reviewer — whichever ran — applies this rubric:
   - (a) **coverage** — every `R##`/`I##`/`C##` maps to ≥1 task, and every GRILL `S##` marked covered by a `D##`/`C##` maps to ≥1 task or is explicitly out of scope (negative-space `S##` excepted);
   - (b) **ordering** — no task depends on later work; prerequisites present;
   - (c) **granularity** — each task is independently implementable and testable;
   - (d) **missing cross-cutting work**;
   - (e) the first milestone is a true end-to-end vertical slice.

   Require the reviewer to classify each finding `blocking | non-blocking | style`. Only `blocking` findings trigger a revision and another round. Stop at the first clean round; **cap at 2 rounds**. If blocking findings remain after 2 rounds, write the plan `status: draft` with a review caveat and surface that the PRD/GRILL inputs are likely underspecified. Only fail closed — refuse to write a PLAN at all — if **no** reviewer can run (neither Codex nor a subagent); report that as a tool/infrastructure failure, not PRD/GRILL underspecification. Otherwise the review always happens, and which reviewer ran is recorded (see step 4).

4. **Write the PLAN.** Save to `.claude/specs/<feature>/PLAN-<timestamp>.md` per the Artifact rules (`type: plan`, `source: [<PRD artifact_id>]`), plus `review: passed | with-caveats` and `reviewed_by: codex | subagent` (the reviewer that actually ran — a `subagent` review is same-model and less independent, so the field lets a reader judge review strength). `blocking_open_items` = the count of unresolved blocking items carried into the plan. Then report the path, the status, the review outcome, and which reviewer ran.

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

A table mapping every `R##`/`I##`/`C##` (and every GRILL `S##` marked covered by a `D##`/`C##`) to the task(s) that satisfy it. This is the coverage guarantee — every requirement, invariant, contract, and decision-covered surface must appear or be explicitly out of scope; negative-space surfaces (`considered — no decision` / `considered — N/A`) are listed as such.

## Risks & Assumptions

Open risks and assumptions carried into implementation.

## Review Summary

`reviewed_by` (codex or subagent) and the `review` outcome, the blocking findings the reviewer raised, and how each was resolved.

</plan-template>

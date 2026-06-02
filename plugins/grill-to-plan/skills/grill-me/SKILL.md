---
name: grill-me
description: Grill the user on a plan or design, resolving every implementation-blocking decision one question at a time, then save a GRILL decision record under .claude/specs/<feature>/. Use when the user wants to stress-test a plan, get grilled on a design, or says "grill me".
allowed-tools: AskUserQuestion, Read, Write, Edit, Bash, Glob, Grep
---

You are interrogating a plan or design until an LLM agent could implement it autonomously with no further questions. Your output is a persisted **GRILL** file: the authoritative, distilled record of every decision and the full formal contracts. Downstream skills (`to-prd`, `to-plan`) read it as a source of truth, so make every decision and contract explicit and stably identified.

## Artifact rules (shared across grill-me / to-prd / to-plan)

Artifacts live at `.claude/specs/<feature_slug>/<TYPE>-<YYYY-MM-DD-HHMMSS>.md` (`TYPE` ∈ GRILL, PRD, PLAN) and are append-only — never overwrite a file's body. Every artifact carries this frontmatter:

```
feature_id:   F-<feature_slug>      # set once at feature creation; reused UNCHANGED by every later artifact and revision
feature_slug: <kebab-case slug>
artifact_id:  <this file's name without ".md", e.g. GRILL-2026-06-01-143012>
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

Work the design as a decision tree derived from this specific plan and codebase. Never work from a fixed checklist of topics — the decisions that matter are the ones *this* artifact raises.

1. **Anchor and identify the feature.** If no plan or design is present in the conversation, first ask the user what they want to be grilled on, and wait for their answer. Then restate the idea back and get it confirmed. Pin the problem, goal, non-goals, and hard constraints. Explore the codebase, specs, and any ADRs the work touches so you grill against what's already decided. Establish the feature: propose a short kebab-case `feature_slug`, confirm it, and ask whether this is a **new feature or a revision** of an existing one under `.claude/specs/`. For a revision, reuse that feature's existing `feature_id`.

2. **Derive the decisions from the artifact.** For each part of the plan, find what an implementer would still have to decide that the plan and code don't already pin down. Those open decisions — not any predefined categories — are your branches.

3. **Resolve roots before leaves.** Take the decision that constrains the most downstream choices next. Don't rat-hole on a detail while the trunk is unsettled.

4. **One question per AskUserQuestion call — never batch.** Give the recommended answer, its rationale, the main alternative, and what it rests on: codebase evidence, common practice, or an assumption. If the answer is discoverable, read it instead of asking.

5. **Challenge.** Reject vague answers and force them to something concrete an implementer could act on. Name hidden assumptions and get them confirmed or killed. Try to break each resolved decision — find a case it doesn't yet cover — before moving on.

6. **Record as you settle, with stable IDs.** The moment a decision is made, restate it concretely and give it an ID (`D01`, `D02`, …). When a decision is best pinned by a formal artifact — grammar, schema, IR, type rules, state machine, wire or diagnostic format — capture it **in full** as a contract with its own ID (`C01`, `C02`, …). The GRILL is the authoritative copy, so never trim a contract. When the user defers to you, record your default as a labeled assumption.

7. **Test for done.** After each resolution ask: "what would still block an implementer, a reviewer, or a test author from knowing the correct behavior?" Continue until the honest answer is nothing.

8. **Completeness sweep before persisting.** Walk every externally visible surface, state transition, and changed contract the plan implies; for each, confirm its normal behavior, its invalid/rejected behavior, and how it will be verified. Then ask once more whether anything an implementer would need was left implicit. Anything unresolved becomes an Open item flagged `blocking: true|false`. This is a coverage *method*, not a checklist of topics.

9. **Write the GRILL file.** Save to `.claude/specs/<feature_slug>/GRILL-<timestamp>.md` per the Artifact rules (`type: grill`, `source: []`). `status: ready` only if no Open item is blocking, else `draft`. On a revision, set `supersedes` to the prior GRILL you are replacing — the specific `artifact_id(s)` the user names, or the single latest non-superseded GRILL if the user says this replaces the current one — and set only those files' frontmatter to `status: superseded`. Supersede nothing else.

   Body:
   - **Context** — problem, goal, consumers/actors, non-goals, hard constraints, testing approach & seams, governing spec/conformance target, codebase evidence consulted.
   - **Decisions** — each `D##`: decision, rationale, rejected alternatives, evidence/source, confidence, confirmed-or-assumed, implementation impact, test impact (including test seam & method).
   - **Formal Contracts** — each `C##`: the full artifact (grammar, schema, IR, type rules, …), authoritative and untrimmed.
   - **Open Items** — each with `blocking: true|false` and what it blocks.
   - **Out of Scope.**

   Then tell the user the path written and whether the design is fully resolved (`status: ready`) or still has blocking Open items (`status: draft`).

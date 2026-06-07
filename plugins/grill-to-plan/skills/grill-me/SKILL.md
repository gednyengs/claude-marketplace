---
name: grill-me
description: Grill the user on a plan or design, resolving every implementation-blocking decision one question at a time, then save a GRILL decision record under .claude/grill-me/specs/<feature>/. Use when the user wants to stress-test a plan, get grilled on a design, or says "grill me".
allowed-tools: AskUserQuestion, Read, Write, Edit, Bash, Glob, Grep
---

You are interrogating a plan or design until an LLM agent could implement it autonomously with no further questions. Your output is a persisted **GRILL** file: the authoritative, distilled record of every decision and the full formal contracts. Downstream skills (`draft-prd`, `draft-plan`) read it as a source of truth, so make every decision and contract explicit and stably identified.

## Artifact rules (shared across grill-me / draft-prd / draft-plan)

Artifacts live at `.claude/grill-me/specs/<feature_slug>/<TYPE>-<YYYY-MM-DD-HHMMSS>.md` (`TYPE` ∈ GRILL, PRD, PLAN) and are append-only — never overwrite a file's body. Every artifact carries this frontmatter:

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
- **Resolve `<feature>`** by exact folder-name match under `.claude/grill-me/specs/` only. No exact match → list candidates and stop. Multiple partial matches → stop and ask. Never guess.
- **Latest** artifact of a type = highest `created` among those whose `status` ≠ `superseded`. Tie → lexicographically greatest filename. Still ambiguous → stop and ask the user to name it.
- **`stale: true` ⇒ the artifact cannot be `ready`.** An artifact is stale when its `source` is not the latest non-superseded artifact (of the source's type) for the feature.
- **Provenance** — every surface, decision, and formal contract is tagged with where its truth comes from: `code-confirmed` (read from existing code/tests), `spec-derived` (fixed by an external standard, governing spec, or reference implementation), `design-intended` (asserted by the plan/design but not yet built), or `assumed` (your default, recorded because the user deferred). Provenance lives on the surface/decision/contract, not in frontmatter.
- Only the artifact currently being written may be `draft` or `ready`; an older artifact may be set `superseded` only when explicitly replaced.

---

Work the design as a decision tree derived from this specific plan and its grounding. Never work from a fixed checklist of topics — the decisions that matter are the ones *this* artifact raises.

**Scale to blast radius.** Match the depth of interrogation to what a wrong decision would cost: a copy tweak or an isolated helper does not need the full machinery; a migration, an auth boundary, a payment path, or a concurrency change does. Calibrate, but never skip the recall sweep, the assumption audit, or the consistency pass — for low-risk work each may be terse, but it must still be explicit.

1. **Anchor the feature, then establish grounding.** If no plan or design is present in the conversation, first ask the user what they want to be grilled on, and wait for their answer. Then restate the idea back and get it confirmed. Pin the problem, goal, non-goals, and hard constraints. **Establish grounding from whatever authoritative sources exist** — on a spectrum from existing code/specs/ADRs (*brownfield*), through an external standard, reference implementation, or governing spec (*conformance work*), to first-principles derivation from the stated requirements and domain conventions (*greenfield*). **There may be no codebase; never treat one as a precondition** — when there is nothing to read, every answer comes from the user or is recorded as a labeled assumption, so the assumption audit (step 9) carries more weight, not less. Tag each thing you learn with its provenance. Then establish the feature: propose a short kebab-case `feature_slug`, confirm it, and ask whether this is a **new feature or a revision** of an existing one under `.claude/grill-me/specs/`. For a revision, reuse that feature's existing `feature_id`.

2. **Inventory the surfaces.** From the grounding, build an explicit inventory of every surface this feature touches or introduces — APIs, CLI commands, data stores & migrations, events/messages, files & formats, permissions, background jobs, config, UI states, logs/metrics, error & diagnostic outputs. Give each a stable ID (`S01`, `S02`, …) and a provenance tag (`code-confirmed` when discovered from code; `design-intended` when it's a surface the design *will* create). Your questions come from the **gap** between this inventory and what the plan already pins down. Record surfaces you considered that need no decision too, tagged `considered — no decision` (or `considered — N/A`), so the inventory doubles as a negative-space record of what was deliberately left alone. This is a grounding-derived map — from code in brownfield, from the design in greenfield — not a topic checklist.

3. **Derive the decisions.** For each surface and each part of the plan, find what an implementer would still have to decide that the grounding doesn't already pin down. Those open decisions — not any predefined categories — are your branches. Tie each branch to the `S##` it arises from where one applies.

4. **Resolve roots before leaves.** Take the decision that constrains the most downstream choices next. Don't rat-hole on a detail while the trunk is unsettled.

5. **One question per AskUserQuestion call — never batch.** Give the recommended answer, its rationale, the main alternative, and what it rests on: grounding evidence, common practice, or an assumption. **Also state the strongest case *against* your recommendation** — the scenario in which it's the wrong call — so your recommendation informs without anchoring. If the answer is discoverable from the grounding, read it instead of asking.

6. **Challenge.** Reject vague answers and force them to something concrete an implementer could act on. Name hidden assumptions and get them confirmed or killed. Try to break each resolved decision — find a case it doesn't yet cover — before moving on.

7. **Record as you settle, with stable IDs — and backtrack when a root shifts.** The moment a decision is made, restate it concretely and give it an ID (`D01`, `D02`, …) with its provenance tag. When a decision is best pinned by a formal artifact — grammar, schema, IR, type rules, state machine, wire or diagnostic format — capture it **in full** as a contract with its own ID (`C01`, `C02`, …) and its provenance (`spec-derived` when it comes from a governing spec or reference implementation, else `design-intended`). The GRILL is the authoritative copy, so never trim a contract. When the user defers to you, record your default as an `assumed` decision. **Backtrack** whenever a later decision narrows or contradicts an earlier root, a new contract appears, or an assumption becomes confirmed: revisit the affected `D##` (and `S##`) and reconcile them. Don't let the tree stay internally coherent around a wrong root.

8. **Recall sweep — derive, then critique through lenses, then loop.** After resolving the plan-derived tree, pass it through critique lenses — security/authz, data lifecycle & migration/rollback, failure & partial-failure modes, concurrency/ordering/idempotency, compatibility & versioning, observability/operability, performance & limits, testing seams, API/UX contract — treating each as a **minimum recall probe, not a topic to fill in**, plus any further lens the Surface Inventory itself suggests. A lens earns a question only when it raises a decision *this* design actually needs; lenses that don't apply are noted `considered — N/A`, never forced. This is a coverage *method*, not a checklist of topics. For every surface (`S##`) that carries a decision, every state transition, and every changed contract, confirm its normal behavior, its invalid/rejected behavior, and how it will be verified. Then **loop**: repeat the find-missing pass — varying the lens or the consumer role (implementer, reviewer, test author, operator) each time — until two consecutive passes surface no new blocking decision. Anything still unresolved becomes an Open item flagged `blocking: true|false`.

9. **Audit the assumptions.** Collect every decision and surface tagged `assumed`. For each, ask: is it **load-bearing** (would a wrong guess break the design)? Is it **discoverable** from the grounding? A discoverable assumption must be verified and re-tagged; one that can't be resolved now but is load-bearing is promoted to a blocking Open item. A design that rests on unaudited assumptions is not `ready`.

10. **Reconcile the record.** Before persisting, cross-check the whole artifact for contradictions: decision vs decision, contract vs decision, contract vs testing approach, decisions vs non-goals. Confirm every `C##` traces to a `D##`, and every touched or introduced surface (`S##`) is covered by a decision **and** a verification, or is explicitly `considered — no decision`. Any contradiction or orphan is resolved or recorded as a blocking Open item. Then ask once more whether anything an implementer would need was left implicit.

11. **Write the GRILL file.** Save to `.claude/grill-me/specs/<feature_slug>/GRILL-<timestamp>.md` per the Artifact rules (`type: grill`, `source: []`). `status: ready` only if no Open item is blocking **and** the assumption audit and consistency pass left nothing blocking; else `draft`. On a revision, set `supersedes` to the prior GRILL you are replacing — the specific `artifact_id(s)` the user names, or the single latest non-superseded GRILL if the user says this replaces the current one — and set only those files' frontmatter to `status: superseded`. Supersede nothing else.

   Body:
   - **Context** — problem, goal, consumers/actors, non-goals, hard constraints, testing approach & seams, governing spec/conformance target, grounding sources consulted and their provenance.
   - **Surface Inventory** — each `S##`: surface, provenance, and the decision(s)/contract(s) covering it — or `considered — no decision` / `considered — N/A` with a one-line why.
   - **Decisions** — each `D##`: decision, rationale, rejected alternatives, evidence/source, provenance (`code-confirmed | spec-derived | design-intended | assumed`), confidence, implementation impact, test impact (including test seam & method), surfaces touched (`S##`).
   - **Formal Contracts** — each `C##`: the full artifact (grammar, schema, IR, type rules, …) and its provenance, authoritative and untrimmed.
   - **Open Items** — each with `blocking: true|false` and what it blocks.
   - **Out of Scope.**

   Then tell the user the path written and whether the design is fully resolved (`status: ready`) or still has blocking Open items (`status: draft`).

# Grill to Plan

Turn a raw idea into an agent-ready implementation plan through rigorous, adversarial
design interrogation — captured as a traceable, append-only artifact chain.

Three skills form a pipeline:

1. **`grill-me`** — interrogates your plan or design one decision at a time, challenging
   vague answers and stress-testing each choice, until an LLM agent could implement it with
   no further questions. It inventories every surface the work touches, derives the decision
   tree from that, then hardens coverage with a lens-based recall sweep, an assumption audit,
   and a consistency pass. Works greenfield (no codebase required) — every surface and decision
   is tagged with its **provenance** (`code-confirmed` / `spec-derived` / `design-intended` /
   `assumed`). Writes a **GRILL** decision record (surface inventory, full formal contracts,
   rationale, rejected alternatives, confidence).
2. **`to-prd`** — synthesizes a **PRD** from the GRILL. It never interviews and never invents
   a decision; it fails closed, refusing to mark a PRD ready while decisions are open.
3. **`to-plan`** — turns the PRD into a dependency-ordered **PLAN** of implementation tasks.
   A read-only Plan architect subagent drafts it; a bounded independent review loop hardens it — an
   in-model subagent by default, or an external reviewer you supply via a reviewer instruction (for
   a cross-model review).

## The artifact chain

Every run writes an append-only, timestamped file under `.claude/specs/<feature>/`:

```
.claude/specs/<feature>/
  GRILL-<timestamp>.md   surface inventory + decisions + full formal contracts (source of truth)
  PRD-<timestamp>.md     behavioral spec; references GRILL contracts by id
  PLAN-<timestamp>.md    tasks, each citing the requirement/contract it satisfies
```

Files are linked by frontmatter (`source`, `supersedes`) and carry a machine-checkable
`status` (`draft | ready | superseded`). Downstream stages gate on the whole chain and refuse
to advance on an unresolved or stale source. Stable IDs (`S##`/`D##`/`C##` → `R##`/`I##` → `T##`)
give end-to-end traceability from any task back to the decision that justifies it.

## Usage

- **Grill:** "grill me on this design", or invoke `grill-to-plan:grill-me`.
- **PRD:** after grilling, invoke `grill-to-plan:to-prd`.
- **Plan:** after the PRD, invoke `grill-to-plan:to-plan`.

## Requirements

- **`to-plan` reviews the plan with an in-model subagent by default** — nothing leaves your
  environment. To get an *external* (e.g. cross-model) review instead, supply a **reviewer
  instruction**, either as an argument to the run or as a standing preference in your project's
  `CLAUDE.md`. Supplying such an instruction is what sends your PRD, GRILL contracts, and draft
  plan to that external service; an external reviewer falls back to the subagent if it's
  unavailable, and the plan records `reviewed_by` so a `ready` plan reflects which review it got.
  No skill has a hard external dependency; `grill-me` and `to-prd` use none.
  - *Optional example (external review via a separate Codex runner):* if you have installed a
    `codex-runner` skill and the `codex` CLI, your reviewer instruction can be
    `review via the codex-runner skill`. The plugin does **not** ship `codex-runner` — it's an
    optional, separately-installed integration, and the plugin works fully without it.

## Design notes

- **General-purpose, greenfield-ready.** The skills name zero domain categories; the decision
  tree is derived from your specific plan and its grounding — existing code, an external spec, or
  first principles when there is no codebase yet — so they work equally on a compiler, a web app,
  or a CLI, brownfield or from scratch.
- **Fail closed everywhere.** A blocking open decision in the GRILL propagates to a `draft`
  PRD and halts `to-plan` — nothing builds a plan on an unresolved design.

## License

MIT

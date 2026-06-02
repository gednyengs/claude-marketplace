# Grill to Plan

Turn a raw idea into an agent-ready implementation plan through rigorous, adversarial
design interrogation — captured as a traceable, append-only artifact chain.

Three skills form a pipeline:

1. **`grill-me`** — interrogates your plan or design one decision at a time, challenging
   vague answers and stress-testing each choice, until an LLM agent could implement it with
   no further questions. Writes a **GRILL** decision record (full formal contracts,
   rationale, rejected alternatives, confidence).
2. **`to-prd`** — synthesizes a **PRD** from the GRILL. It never interviews and never invents
   a decision; it fails closed, refusing to mark a PRD ready while decisions are open.
3. **`to-plan`** — turns the PRD into a dependency-ordered **PLAN** of implementation tasks.
   A read-only Plan architect subagent drafts it; a bounded Codex review loop hardens it.

## The artifact chain

Every run writes an append-only, timestamped file under `.claude/specs/<feature>/`:

```
.claude/specs/<feature>/
  GRILL-<timestamp>.md   decisions + full formal contracts (the source of truth)
  PRD-<timestamp>.md     behavioral spec; references GRILL contracts by id
  PLAN-<timestamp>.md    tasks, each citing the requirement/contract it satisfies
```

Files are linked by frontmatter (`source`, `supersedes`) and carry a machine-checkable
`status` (`draft | ready | superseded`). Downstream stages gate on the whole chain and refuse
to advance on an unresolved or stale source. Stable IDs (`D##`/`C##` → `R##`/`I##` → `T##`)
give end-to-end traceability from any task back to the decision that justifies it.

## Usage

- **Grill:** "grill me on this design", or invoke `grill-to-plan:grill-me`.
- **PRD:** after grilling, invoke `grill-to-plan:to-prd`.
- **Plan:** after the PRD, invoke `grill-to-plan:to-plan`.

## Requirements

- **`to-plan` requires the `codex-runner` skill and the `codex` CLI** for its review loop. If
  either is unavailable, `to-plan` fails closed — it still drafts the plan but marks it
  `draft` rather than `ready`, and reports that review could not run. `grill-me` and `to-prd`
  have no external dependencies.

## Design notes

- **General-purpose.** The skills name zero domain categories; the decision tree is derived
  from your specific plan and codebase, so they work equally on a compiler, a web app, or a CLI.
- **Fail closed everywhere.** A blocking open decision in the GRILL propagates to a `draft`
  PRD and halts `to-plan` — nothing builds a plan on an unresolved design.

## License

MIT

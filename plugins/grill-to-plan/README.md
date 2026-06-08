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
2. **`draft-prd`** — synthesizes a **PRD** from the GRILL. It never interviews and never invents
   a decision; it fails closed, refusing to mark a PRD ready while decisions are open.
3. **`draft-plan`** — turns the PRD into a dependency-ordered **PLAN** of implementation tasks.
   A read-only Plan architect subagent drafts it; a bounded independent review loop hardens it — an
   in-model subagent by default, or an external reviewer you supply via a reviewer instruction (for
   a cross-model review).

## The artifact chain

Every run writes an append-only, timestamped file under `.claude/sekekama/grill-to-plan/specs/<feature>/`:

```
.claude/sekekama/grill-to-plan/specs/<feature>/
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
- **PRD:** after grilling, invoke `grill-to-plan:draft-prd`.
- **Plan:** after the PRD, invoke `grill-to-plan:draft-plan`.

## Example

A short end-to-end run for the feature *"add a `--json` flag to the `report` CLI command."*

**1. `grill-me`** inventories the surfaces it touches and interrogates the open decisions one at a time:

> **You:** grill me on adding a `--json` flag to `report`
> **grill-me:** With `--json` set, is human-formatted output suppressed entirely, or sent to stderr? *(Recommended: suppress — stdout becomes machine-readable JSON only. Alternative: stderr, which risks mixed formats. Basis: common CLI convention — assumed.)*
> **You:** suppress it.

It writes `GRILL-<timestamp>.md`. Abbreviated excerpts (a real `Decisions` entry also records rationale, rejected alternatives, evidence, confidence, and test impact):

```
## Surface Inventory
- S01  report CLI command   — code-confirmed — covered by D01
- S02  stdout format        — code-confirmed — covered by D01
- S03  exit codes           — code-confirmed — considered — no decision — unchanged

## Decisions
- D01  --json emits one JSON object on stdout; human output suppressed.  provenance: assumed
```

**2. `draft-prd`** reads that GRILL (no re-interview) and emits a behavioral spec (excerpt):

```
R01.  Given --json, when report runs, stdout MUST be a single valid JSON object
      with no human-formatted text.  (covers S01, S02; see GRILL D01)
```

**3. `draft-plan`** has the Plan architect draft tasks, then a reviewer hardens them. Excerpt — PLAN frontmatter plus one task:

```
# frontmatter:  status: ready   review: passed   reviewed_by: subagent
T01  Scope: add --json parsing + JSON emitter to report
     Depends-on: —
     Acceptance: R01 (realizes S01, S02)
     Test: CLI invocation seam, golden-output assertion
     Size: S
```

All three files land under `.claude/sekekama/grill-to-plan/specs/report-json-flag/`, linked by `source`/`supersedes`
frontmatter — so any task (`T01`) traces back through `R01` → `D01` to the decision that justifies it.
Whether you commit that directory is your call; committing preserves the full lineage across clones.

## Requirements

- **`draft-plan` reviews the plan with an in-model subagent by default** — nothing leaves your
  environment. To get an *external* (e.g. cross-model) review instead, supply a **reviewer
  instruction**, either as an argument to the run or as a standing preference in your project's
  `CLAUDE.md`. Supplying such an instruction is what sends your PRD, GRILL contracts, and draft
  plan to that external service; an external reviewer falls back to the subagent if it's
  unavailable, and the plan records `reviewed_by` so a `ready` plan reflects which review it got.
  No skill has a hard external dependency; `grill-me` and `draft-prd` use none.
  - *Optional example (external review via a separately-installed reviewer):* if you have your own
    reviewer skill or CLI installed, your reviewer instruction can name it in plain language — for
    example, `review via the <your-reviewer> skill`. The plugin ships **no** external reviewer of
    its own; any such integration is optional and separately installed, and the plugin works fully
    without one.
- **Unix `date`.** The skills timestamp artifacts with `date +%Y-%m-%d-%H%M%S`. On Windows, run
  Claude Code from a shell that provides the Unix `date` command (Git Bash or WSL).

## Design notes

- **General-purpose, greenfield-ready.** The skills name zero domain categories; the decision
  tree is derived from your specific plan and its grounding — existing code, an external spec, or
  first principles when there is no codebase yet — so they work equally on a compiler, a web app,
  or a CLI, brownfield or from scratch.
- **Fail closed everywhere.** A blocking open decision in the GRILL propagates to a `draft`
  PRD and halts `draft-plan` — nothing builds a plan on an unresolved design.

## License

MIT

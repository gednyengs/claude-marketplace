# Example artifact chain

A complete, illustrative **GRILL → PRD → PLAN** chain produced by `grill-to-plan` for the feature
*"add a `--json` flag to the `report` CLI command."* These are sample outputs so you can see the
artifact formats and the end-to-end traceability **without running the pipeline**.

| File | What it is |
| --- | --- |
| [`report-json-flag/GRILL-2026-06-07-101500.md`](report-json-flag/GRILL-2026-06-07-101500.md) | decisions + surface inventory + formal contracts (source of truth) |
| [`report-json-flag/PRD-2026-06-07-102000.md`](report-json-flag/PRD-2026-06-07-102000.md) | behavioral spec; references GRILL contracts by id |
| [`report-json-flag/PLAN-2026-06-07-103000.md`](report-json-flag/PLAN-2026-06-07-103000.md) | dependency-ordered tasks + traceability table |

Trace any task back to the decision that justifies it: **`PLAN T01` → `PRD R02` → `GRILL D01`**
(realizing surfaces `S01`/`S02`). The files are linked by their `source` frontmatter
(`PLAN.source = [PRD]`, `PRD.source = [GRILL]`).

In a real run these live under `.claude/grill-me/specs/<feature>/`; here they're checked in as a
reference. They are illustrative — a real grilling session would typically surface more decisions.

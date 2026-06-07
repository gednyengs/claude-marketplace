# Changelog

All notable changes to this plugin are documented here. This project follows
[semantic versioning](https://semver.org).

## [3.0.0] — 2026-06-07

### Changed (breaking)
- Artifacts now live under `.claude/sekekama/grill-to-plan/specs/<feature>/` (was
  `.claude/grill-me/specs/<feature>/`). This adopts the shared `.claude/sekekama/<plugin>/`
  layout used across the sekekama plugins (the same namespacing as `session-handoff`), so every
  plugin's artifacts sit under one org-scoped directory instead of each carving its own top-level
  `.claude/` folder.
- Existing chains under the old path are **not migrated automatically** — move them with
  `git mv .claude/grill-me/specs .claude/sekekama/grill-to-plan/specs` (creating
  `.claude/sekekama/grill-to-plan/` first), or a plain `mv`, if you want them found. The skills
  resolve features under the new path only.

## [2.1.1] — 2026-06-07

### Changed
- Consistency fixes from a final read-through: `draft-plan` gained an **Open Items** section so
  `blocking_open_items` has a referent; `draft-prd`/`draft-plan` wording no longer assumes a
  codebase exists (greenfield parity with `grill-me`); clarified the `grill-me` recall-sweep
  phrasing; `draft-plan` Review Summary now notes an external-reviewer → subagent fallback.

## [2.1.0] — 2026-06-07

### Added
- Checked-in example artifact chain at `examples/report-json-flag/` (GRILL → PRD → PLAN) so users
  can browse the formats and end-to-end traceability without running the pipeline.

### Changed
- README: documented that the skills timestamp artifacts via the Unix `date` command (on Windows,
  run Claude Code from Git Bash or WSL). The shared "Artifact rules" block is intentionally kept
  inline in each skill (always-needed core contract; referenced files load only on demand).

## [2.0.0] — 2026-06-07

### Changed (breaking)
- Renamed skills for clearer slash commands: `to-prd` → `draft-prd` and `to-plan` → `draft-plan`
  (`grill-me` unchanged). Invoke them as `grill-to-plan:draft-prd` / `grill-to-plan:draft-plan`.
- Artifacts now live under `.claude/grill-me/specs/<feature>/` (was `.claude/specs/<feature>/`).
  Existing chains under the old path are not migrated automatically; move them if you want them found.

### Added
- Plugin manifest now declares `homepage`, `repository`, and `bugs` for discovery and support.
- README: a worked end-to-end example (GRILL → PRD → PLAN) plus clearer reviewer and usage docs.

## [1.3.0] — 2026-06-07

### Changed
- `to-plan`: simplified and decoupled the reviewer model. Review runs through an in-model
  `general-purpose` subagent by default (no external egress); an external reviewer runs only when
  the caller supplies a **reviewer instruction** — as a run argument or a standing preference (e.g.
  in `CLAUDE.md`) — which is itself the consent to send content externally. This removes the
  interactive consent prompt and **all hard-coded references to any specific external tool**, so
  the plugin no longer names a private dependency (`codex-runner` is now only an optional README
  example). An external reviewer falls back to the subagent on failure, the reviewer is locked for
  both rounds, and the plan records `reviewed_by`. Supersedes the 1.2.0 consent-prompt approach.

## [1.2.0] — 2026-06-07

### Changed
- `to-plan`: the plan review loop is now reviewer-agnostic and privacy-safe by default. It
  reviews with an in-model `general-purpose` subagent by default — nothing leaves the environment
  — and uses an external cross-model review via Codex (the `codex-runner` skill) only with the
  user's consent: when `codex-runner` is available and the session is interactive it asks once
  which reviewer to use, and otherwise (absent, non-interactive, or declined) falls back to the
  subagent. The skill no longer hard-depends on Codex or fails closed when Codex is absent. The
  reviewer that ran is recorded on the PLAN as `reviewed_by: codex | subagent`; the same rubric
  and 2-round cap apply either way.

## [1.1.0] — 2026-06-05

### Added
- `grill-me`: **Surface Inventory** — every touched or introduced surface gets a stable `S##`
  ID, provenance, and a negative-space record of surfaces deliberately left alone.
- `grill-me`: **provenance** tags (`code-confirmed` / `spec-derived` / `design-intended` /
  `assumed`) on every surface, decision, and contract — the basis for greenfield support and
  the assumption audit.
- `grill-me`: oracle-free recall hardening — a lens-based recall sweep that loops until dry,
  backtracking triggers, an assumption audit, a consistency pass, anti-anchoring on
  recommendations, and blast-radius calibration.
- `to-prd` / `to-plan`: consume the Surface Inventory and provenance — PRD requirements and
  PLAN traceability now account for every decision-covered `S##` (negative-space surfaces are
  preserved, never invented into requirements); PRD Assumptions flow from `assumed` provenance
  and Conformance from `spec-derived`.

### Changed
- `grill-me` no longer assumes a codebase exists; grounding is established from whatever
  authoritative sources are available — existing code, an external spec, or first principles.

## [1.0.0] — 2026-06-01

### Added
- Initial release: `grill-me`, `to-prd`, and `to-plan` skills forming a GRILL → PRD → PLAN
  pipeline that takes a design from interrogation to an agent-ready implementation plan.
- Append-only, traceable artifact chain under `.claude/specs/<feature>/` with machine-checkable
  `status`, lineage (`source`/`supersedes`), and stable IDs (`D##`/`C##` → `R##`/`I##` → `T##`).
- Whole-chain fail-closed gates, and a bounded (2-round) Codex review loop in `to-plan`.

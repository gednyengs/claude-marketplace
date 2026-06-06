# Changelog

All notable changes to this plugin are documented here. This project follows
[semantic versioning](https://semver.org).

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

# Changelog

All notable changes to this plugin are documented here. This project follows
[semantic versioning](https://semver.org).

## [1.0.0] — 2026-06-01

### Added
- Initial release: `grill-me`, `to-prd`, and `to-plan` skills forming a GRILL → PRD → PLAN
  pipeline that takes a design from interrogation to an agent-ready implementation plan.
- Append-only, traceable artifact chain under `.claude/specs/<feature>/` with machine-checkable
  `status`, lineage (`source`/`supersedes`), and stable IDs (`D##`/`C##` → `R##`/`I##` → `T##`).
- Whole-chain fail-closed gates, and a bounded (2-round) Codex review loop in `to-plan`.

# Contributing

Thanks for your interest in contributing to this Claude Code plugin marketplace.

## Repository layout

```
.claude-plugin/marketplace.json   marketplace manifest (lists every plugin)
plugins/<plugin>/                  one directory per plugin
  .claude-plugin/plugin.json       plugin manifest
  skills/ commands/ hooks/ ...      plugin components
```

## Ways to contribute

- Report a bug or request a feature using the issue templates.
- Improve an existing plugin (a skill, command, hook, or its docs).
- Propose a new plugin.

## Developing locally

1. Fork and clone the repository.
2. Add your clone as a local marketplace so you can test changes:
   ```
   /plugin marketplace add /path/to/your/clone
   ```
3. Make changes under `plugins/<plugin>/`.
4. Validate the manifest:
   ```
   claude plugin validate plugins/<plugin>
   ```
5. Enable the plugin from your local marketplace and exercise the skills or
   commands you changed.

## Pull requests

- Keep each PR focused on a single change.
- When behavior changes, bump the plugin's `version` in `plugin.json` and update
  its `CHANGELOG.md`.
- Use clear, conventional commit messages, e.g. `feat(<plugin>): ...`,
  `fix(<plugin>): ...`, `docs: ...`.
- Fill out the pull request template.

## Code of conduct

By participating you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

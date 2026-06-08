# Security Policy

## Reporting a vulnerability

Please do not report security vulnerabilities through public GitHub issues.

Instead, use GitHub's private vulnerability reporting:

1. Open the **Security** tab of this repository.
2. Click **Report a vulnerability**.
3. Include a description, reproduction steps, and which plugin(s) are affected.

You can expect an initial response within a reasonable timeframe. If a report is
accepted, a fix will be prepared and released, and the issue disclosed once a fix
is available.

## Scope

These plugins are local Claude Code extensions (skills, commands, and hooks) that
run in your own environment; there is no hosted service. The most relevant concerns
are therefore:

- Shell commands or hooks that could run unintended actions on a user's machine.
- Handling of file paths or untrusted input that could lead to unintended file
  access or writes.

## Supported versions

Releases are cut from the `main` branch. The latest published version of each
plugin receives fixes.

# sekekama

Claude Code plugins by Gedeon Nyengele, distributed as a [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces).

## Install the marketplace

Inside Claude Code:

```
/plugin marketplace add gednyengs/claude-marketplace
```

Or by full git URL:

```
/plugin marketplace add git@github.com:gednyengs/claude-marketplace.git
```

## Install a plugin

```
/plugin install <plugin-name>@sekekama
```

After installing, run `/reload-plugins` (or restart Claude Code) so the new components are picked up.

## Available plugins

| Plugin | Description |
| --- | --- |
| [`session-handoff`](plugins/session-handoff) | Save and restore working context across Claude Code sessions and context compaction. |

## Local development

To work on a plugin in this repo without going through GitHub, point Claude Code at your local clone:

```
/plugin marketplace add /absolute/path/to/claude-marketplace
/plugin install session-handoff@sekekama
```

Validate the marketplace and any plugin before pushing:

```
claude plugin validate .
claude plugin validate ./plugins/session-handoff
```

## License

MIT (see [LICENSE](LICENSE)).

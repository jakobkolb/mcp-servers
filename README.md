# mcp-servers

A Python monorepo of [Model Context Protocol](https://modelcontextprotocol.io) (MCP) servers — primarily for personal productivity tooling (Obsidian, CalDAV, and others).

Each server lives under `servers/<name>/`, ships as a Docker container, and is managed via a shared [uv workspace](https://docs.astral.sh/uv/concepts/workspaces/).

## Servers

| Server | Type | Description |
|--------|------|-------------|
| [mcp-obsidian](servers/mcp-obsidian/) | Tool + Resource | Interact with Obsidian via the Local REST API plugin |
| [mcp-calendar](servers/mcp-calendar/) | Tool | Unified CalDAV view of iCloud, Gmail, and Nextcloud calendars |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package and workspace manager
- [Docker](https://docs.docker.com/) — for building and running server images
- [pre-commit](https://pre-commit.com/) — for local linting hooks

## Getting started

```bash
# Install all workspace dependencies
make install

# Install pre-commit hooks
pre-commit install
```

## Development workflow

```bash
make install    # sync all workspace packages
make lint       # ruff + mypy across all servers
make test       # pytest across all servers
make build      # docker build for every server
```

Individual server targets accept a `SERVER=<name>` override:

```bash
make test SERVER=obsidian
make build SERVER=caldav
```

## Adding a server

1. Copy the scaffold:
   ```bash
   cp -r servers/example servers/<your-server>
   ```
2. Rename the Python package inside `src/` and update `pyproject.toml` (`name`, `description`, package path).
3. Implement your tools/resources in `src/<your_server>/server.py`.
4. Update the [Servers](#servers) table above.

The workspace root `pyproject.toml` picks up new servers automatically via the `servers/*` glob — no manual registration needed.

## Repository structure

```
mcp-servers/
├── servers/
│   └── example/            # Scaffold — copy this to start a new server
│       ├── src/
│       │   └── example_server/
│       │       ├── __init__.py
│       │       └── server.py
│       ├── tests/
│       │   └── test_server.py
│       ├── Dockerfile
│       ├── pyproject.toml
│       └── README.md
├── .github/
│   └── workflows/
│       └── ci.yml
├── .pre-commit-config.yaml
├── Makefile
└── pyproject.toml          # uv workspace root
```

## License

[MIT](LICENSE)

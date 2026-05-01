# mcp-obsidian

MCP server for interacting with [Obsidian](https://obsidian.md) via the [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) community plugin.

## Prerequisites

Install and enable the **Local REST API** plugin in Obsidian, then copy the API key from its settings panel.

## Tools

| Tool | Description |
|------|-------------|
| `obsidian_list_files_in_vault` | List all files/directories at vault root |
| `obsidian_list_files_in_dir` | List files in a specific directory |
| `obsidian_get_file_contents` | Read a single file |
| `obsidian_batch_get_file_contents` | Read multiple files concatenated |
| `obsidian_simple_search` | Full-text search across the vault |
| `obsidian_complex_search` | JsonLogic query search (glob, regexp, tags) |
| `obsidian_append_content` | Append text to a file (creates if missing) |
| `obsidian_patch_content` | Insert relative to a heading/block/frontmatter |
| `obsidian_put_content` | Create or overwrite a file |
| `obsidian_delete_file` | Delete a file or directory |
| `obsidian_get_periodic_note` | Get current daily/weekly/monthly/etc. note |
| `obsidian_get_recent_periodic_notes` | Get recent periodic notes |
| `obsidian_get_recent_changes` | Get recently modified files (via Dataview DQL) |

## Configuration

| Environment variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `OBSIDIAN_API_KEY` | Yes | — | API key from Local REST API plugin settings |
| `OBSIDIAN_HOST` | No | `127.0.0.1` | Host where Obsidian is running |
| `OBSIDIAN_PORT` | No | `27124` | Port of the Local REST API plugin |
| `OBSIDIAN_PROTOCOL` | No | `https` | `https` or `http` |

Create a `.env` file in the server directory or pass variables at runtime.

## Usage

```bash
# Run directly
OBSIDIAN_API_KEY=your-key uv run mcp-obsidian

# Run via Docker
docker build -t mcp-obsidian:latest .
docker run --rm -i \
  -e OBSIDIAN_API_KEY=your-key \
  -e OBSIDIAN_HOST=host.docker.internal \
  mcp-obsidian:latest
```

## Claude Desktop config

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/servers/mcp-obsidian", "mcp-obsidian"],
      "env": {
        "OBSIDIAN_API_KEY": "your-key-here"
      }
    }
  }
}
```

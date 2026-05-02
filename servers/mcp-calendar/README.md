# mcp-calendar

An MCP server providing a unified view of iCloud, Gmail, and Nextcloud calendars via CalDAV.

## Tools

| Tool | Description |
|------|-------------|
| `calendar_list_calendars` | List all available calendars grouped by backend |
| `calendar_list_events` | List events within a date/time range (optional backend filter) |
| `calendar_create_event` | Create a new event on a specific backend |
| `calendar_update_event` | Update an existing event by UID |
| `calendar_delete_event` | Delete an event by UID |
| `calendar_get_freebusy` | Get busy time slots within a date/time range |

## Configuration

Create a YAML config file (default: `~/.config/mcp-calendar/config.yaml`):

```yaml
calendars:
  # iCloud
  - type: icloud
    name: personal
    username: user@icloud.com
    password: "<your-app-specific-password>"   # app-specific password

  # Gmail / Google Calendar (app password)
  - type: google
    name: work
    username: user@gmail.com
    password: "<your-app-specific-password>"   # app-specific password

  # Nextcloud
  - type: nextcloud
    name: shared
    url: https://cloud.example.com
    username: alice
    password: "<your-password>"
    calendar_name: Family           # optional: filter to a single calendar
    verify_ssl: true                # optional, default true
```

Override the config path with the `CALENDAR_CONFIG` environment variable.

## Running with Docker

```bash
docker run --rm -i \
  -v ~/.config/mcp-calendar:/config:ro \
  mcp-calendar:latest
```

## Claude Desktop config

```json
{
  "mcpServers": {
    "calendar": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/Users/you/.config/mcp-calendar:/config:ro",
        "mcp-calendar:latest"
      ]
    }
  }
}
```

Or if running directly with uv:

```json
{
  "mcpServers": {
    "calendar": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-calendar", "mcp-calendar"],
      "env": {
        "CALENDAR_CONFIG": "/Users/you/.config/mcp-calendar/config.yaml"
      }
    }
  }
}
```

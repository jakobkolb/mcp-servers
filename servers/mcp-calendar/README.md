# mcp-calendar

An MCP server providing a unified view of iCloud, Google, and Nextcloud calendars and task lists via CalDAV.

## Tools

### Events

| Tool | Description |
|------|-------------|
| `calendar_list_calendars` | List all available calendars grouped by backend |
| `calendar_list_events` | List events within a date/time range (optional backend filter) |
| `calendar_create_event` | Create a new event on a specific backend |
| `calendar_update_event` | Update an existing event by UID |
| `calendar_delete_event` | Delete an event by UID |
| `calendar_get_freebusy` | Get busy time slots within a date/time range |

### Tasks (VTODO)

| Tool | Description |
|------|-------------|
| `calendar_list_tasks` | List tasks/reminders across all backends (optional backend and calendar filter) |
| `calendar_create_task` | Create a new task on a specific backend |
| `calendar_update_task` | Update an existing task by UID (summary, due date, priority, status) |
| `calendar_delete_task` | Delete a task by UID |

> **Note:** Google Calendar does not support task write operations (`create_task`, `update_task`, `delete_task`). `list_tasks` returns an empty list for Google backends.

### Reminders / alarms

`calendar_create_event` and `calendar_update_event` both accept an optional `alarms` field — a list of integers representing minutes before the event start when a reminder should fire:

```json
{ "alarms": [15, 60] }
```

Omitting `alarms` in `calendar_update_event` preserves existing reminders. Passing an empty list removes them all.

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
    calendar_name: Family           # optional: filter events to a single calendar
    task_list_filter: My Tasks      # optional: filter tasks to a specific task list
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

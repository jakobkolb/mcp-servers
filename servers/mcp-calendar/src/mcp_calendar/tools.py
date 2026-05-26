from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

from .calendar import CalendarBackend

_backends: list[CalendarBackend] = []

ToolResult = Sequence[TextContent | ImageContent | EmbeddedResource]


def set_backends(backends: list[CalendarBackend]) -> None:
    global _backends
    _backends = backends


class ToolHandler:
    def __init__(self, tool_name: str) -> None:
        self.name = tool_name

    def get_tool_description(self) -> Tool:
        raise NotImplementedError

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class ListCalendarsToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_list_calendars")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="List all available calendars grouped by backend.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        result: dict[str, list[str]] = {}
        for backend in _backends:
            result[backend.name] = backend.list_calendars()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]


class ListEventsToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_list_events")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="List calendar events within a date/time range across all backends.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start": {
                        "type": "string",
                        "description": "Start of range as ISO 8601 datetime string.",
                    },
                    "end": {
                        "type": "string",
                        "description": "End of range as ISO 8601 datetime string.",
                    },
                    "backend": {
                        "type": "string",
                        "description": "Optional backend name to filter results.",
                    },
                },
                "required": ["start", "end"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "start" not in args:
            raise RuntimeError("start argument missing in arguments")
        if "end" not in args:
            raise RuntimeError("end argument missing in arguments")

        start = datetime.fromisoformat(args["start"])
        end = datetime.fromisoformat(args["end"])
        backend_filter: str | None = args.get("backend")

        events = []
        for backend in _backends:
            if backend_filter is not None and backend.name != backend_filter:
                continue
            events.extend(backend.list_events(start, end))

        events.sort(key=lambda e: e.start.isoformat())
        return [TextContent(type="text", text=json.dumps([e.to_dict() for e in events], indent=2))]


class CreateEventToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_create_event")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=(
                "Create a new calendar event on a specific backend. "
                "Supports both timed events (ISO 8601 datetime) and all-day events "
                "(YYYY-MM-DD date strings — omit the time component entirely)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Name of the backend to create the event on.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Title/summary of the event.",
                    },
                    "start": {
                        "type": "string",
                        "description": (
                            "Start of the event. Use YYYY-MM-DD for an all-day event, "
                            "or a full ISO 8601 datetime (e.g. 2024-06-01T10:00:00+02:00) "
                            "for a timed event. Do NOT use T00:00:00 for all-day events."
                        ),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "End of the event. Use YYYY-MM-DD for an all-day event "
                            "(exclusive: the day after the last day), "
                            "or a full ISO 8601 datetime for a timed event."
                        ),
                    },
                    "calendar_name": {
                        "type": "string",
                        "description": "Optional calendar name within the backend.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional event description.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional event location.",
                    },
                    "alarms": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of reminder offsets in minutes before start.",
                    },
                },
                "required": ["backend", "summary", "start", "end"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        for req in ("backend", "summary", "start", "end"):
            if req not in args:
                raise RuntimeError(f"{req} argument missing in arguments")

        backend_name: str = args["backend"]
        backend = next((b for b in _backends if b.name == backend_name), None)
        if backend is None:
            raise RuntimeError(f"Backend '{backend_name}' not found")

        start_str: str = args["start"]
        end_str: str = args["end"]
        start = (
            datetime.fromisoformat(start_str) if "T" in start_str else date.fromisoformat(start_str)
        )
        end = datetime.fromisoformat(end_str) if "T" in end_str else date.fromisoformat(end_str)
        alarms_raw: list[int] | None = args.get("alarms")
        alarms = [timedelta(minutes=m) for m in alarms_raw] if alarms_raw is not None else None

        event = backend.create_event(
            summary=args["summary"],
            start=start,
            end=end,
            calendar_name=args.get("calendar_name"),
            description=args.get("description"),
            location=args.get("location"),
            alarms=alarms,
        )
        return [TextContent(type="text", text=json.dumps(event.to_dict(), indent=2))]


class UpdateEventToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_update_event")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Update an existing calendar event identified by UID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "UID of the event to update.",
                    },
                    "backend": {
                        "type": "string",
                        "description": "Name of the backend that owns the event.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "New event title/summary.",
                    },
                    "start": {
                        "type": "string",
                        "description": (
                            "New start. Use YYYY-MM-DD for an all-day event, "
                            "or a full ISO 8601 datetime for a timed event."
                        ),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "New end. Use YYYY-MM-DD for an all-day event, "
                            "or a full ISO 8601 datetime for a timed event."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "New event description.",
                    },
                    "location": {
                        "type": "string",
                        "description": "New event location.",
                    },
                    "alarms": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "New list of reminder offsets in minutes before start.",
                    },
                },
                "required": ["uid", "backend"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "uid" not in args:
            raise RuntimeError("uid argument missing in arguments")
        if "backend" not in args:
            raise RuntimeError("backend argument missing in arguments")

        backend_name: str = args["backend"]
        backend = next((b for b in _backends if b.name == backend_name), None)
        if backend is None:
            raise RuntimeError(f"Backend '{backend_name}' not found")

        start: datetime | date | None = None
        if "start" in args:
            s = args["start"]
            start = datetime.fromisoformat(s) if "T" in s else date.fromisoformat(s)
        end: datetime | date | None = None
        if "end" in args:
            e = args["end"]
            end = datetime.fromisoformat(e) if "T" in e else date.fromisoformat(e)
        alarms_raw: list[int] | None = args.get("alarms")
        alarms = [timedelta(minutes=m) for m in alarms_raw] if alarms_raw is not None else None

        event = backend.update_event(
            uid=args["uid"],
            summary=args.get("summary"),
            start=start,
            end=end,
            description=args.get("description"),
            location=args.get("location"),
            alarms=alarms,
        )
        return [TextContent(type="text", text=json.dumps(event.to_dict(), indent=2))]


class DeleteEventToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_delete_event")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Delete a calendar event by UID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "UID of the event to delete.",
                    },
                    "backend": {
                        "type": "string",
                        "description": "Name of the backend that owns the event.",
                    },
                },
                "required": ["uid", "backend"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "uid" not in args:
            raise RuntimeError("uid argument missing in arguments")
        if "backend" not in args:
            raise RuntimeError("backend argument missing in arguments")

        backend_name: str = args["backend"]
        backend = next((b for b in _backends if b.name == backend_name), None)
        if backend is None:
            raise RuntimeError(f"Backend '{backend_name}' not found")

        backend.delete_event(args["uid"])
        return [TextContent(type="text", text=f"Successfully deleted event {args['uid']}")]


class GetFreeBusyToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_get_freebusy")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Get busy time slots within a date/time range across all backends.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start": {
                        "type": "string",
                        "description": "Start of range as ISO 8601 datetime string.",
                    },
                    "end": {
                        "type": "string",
                        "description": "End of range as ISO 8601 datetime string.",
                    },
                    "backend": {
                        "type": "string",
                        "description": "Optional backend name to filter results.",
                    },
                },
                "required": ["start", "end"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "start" not in args:
            raise RuntimeError("start argument missing in arguments")
        if "end" not in args:
            raise RuntimeError("end argument missing in arguments")

        start = datetime.fromisoformat(args["start"])
        end = datetime.fromisoformat(args["end"])
        backend_filter: str | None = args.get("backend")

        result: dict[str, list[list[str]]] = {}
        for backend in _backends:
            if backend_filter is not None and backend.name != backend_filter:
                continue
            slots = backend.get_freebusy(start, end)
            result[backend.name] = [
                [slot_start.isoformat(), slot_end.isoformat()] for slot_start, slot_end in slots
            ]

        return [TextContent(type="text", text=json.dumps(result, indent=2))]


class CreateTaskToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_create_task")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Create a new VTODO task/reminder on a specific backend.",
            inputSchema={
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Name of the backend to create the task on.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Title/summary of the task.",
                    },
                    "calendar_name": {
                        "type": "string",
                        "description": "Optional task list / calendar name within the backend.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional task description.",
                    },
                    "due": {
                        "type": "string",
                        "description": (
                            "Optional due date or datetime as ISO 8601 string. "
                            "Use YYYY-MM-DD for a date-only due, or a full datetime "
                            "(e.g. 2024-06-01T09:00:00+02:00) to specify a time of day."
                        ),
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priority 0-9 (0=undefined, 1=highest, 9=lowest).",
                        "minimum": 0,
                        "maximum": 9,
                    },
                },
                "required": ["backend", "summary"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "backend" not in args:
            raise RuntimeError("backend argument missing in arguments")
        if "summary" not in args:
            raise RuntimeError("summary argument missing in arguments")

        backend_name: str = args["backend"]
        backend = next((b for b in _backends if b.name == backend_name), None)
        if backend is None:
            raise RuntimeError(f"Backend '{backend_name}' not found")

        due: date | datetime | None = None
        if "due" in args:
            due_str: str = args["due"]
            due = datetime.fromisoformat(due_str) if "T" in due_str else date.fromisoformat(due_str)

        task = backend.create_task(
            summary=args["summary"],
            calendar_name=args.get("calendar_name"),
            description=args.get("description"),
            due=due,
            priority=args.get("priority", 0),
        )
        return [TextContent(type="text", text=json.dumps(task.to_dict(), indent=2))]


class UpdateTaskToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_update_task")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Update an existing VTODO task identified by UID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "UID of the task to update.",
                    },
                    "backend": {
                        "type": "string",
                        "description": "Name of the backend that owns the task.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "New task title/summary.",
                    },
                    "description": {
                        "type": "string",
                        "description": "New task description.",
                    },
                    "due": {
                        "type": "string",
                        "description": (
                            "New due date or datetime as ISO 8601 string. "
                            "Use YYYY-MM-DD for a date-only due, or a full datetime "
                            "(e.g. 2024-06-01T09:00:00+02:00) to specify a time of day."
                        ),
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priority 0-9 (0=undefined, 1=highest, 9=lowest).",
                        "minimum": 0,
                        "maximum": 9,
                    },
                    "status": {
                        "type": "string",
                        "description": "Task status.",
                        "enum": ["NEEDS-ACTION", "COMPLETED", "IN-PROCESS", "CANCELLED"],
                    },
                },
                "required": ["uid", "backend"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "uid" not in args:
            raise RuntimeError("uid argument missing in arguments")
        if "backend" not in args:
            raise RuntimeError("backend argument missing in arguments")

        backend_name: str = args["backend"]
        backend = next((b for b in _backends if b.name == backend_name), None)
        if backend is None:
            raise RuntimeError(f"Backend '{backend_name}' not found")

        due: date | datetime | None = None
        if "due" in args:
            due_str = args["due"]
            due = datetime.fromisoformat(due_str) if "T" in due_str else date.fromisoformat(due_str)
        priority: int | None = args.get("priority")

        task = backend.update_task(
            uid=args["uid"],
            summary=args.get("summary"),
            description=args.get("description"),
            due=due,
            priority=priority,
            status=args.get("status"),
        )
        return [TextContent(type="text", text=json.dumps(task.to_dict(), indent=2))]


class ListTasksToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_list_tasks")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="List VTODO tasks/reminders across all backends.",
            inputSchema={
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Optional backend name to filter results.",
                    },
                    "calendar_name": {
                        "type": "string",
                        "description": "Optional task list / calendar name to filter results.",
                    },
                },
                "required": [],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        backend_filter: str | None = args.get("backend")
        calendar_name: str | None = args.get("calendar_name")

        tasks = []
        for backend in _backends:
            if backend_filter is not None and backend.name != backend_filter:
                continue
            tasks.extend(backend.list_tasks(calendar_name=calendar_name))

        return [TextContent(type="text", text=json.dumps([t.to_dict() for t in tasks], indent=2))]


class DeleteTaskToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("calendar_delete_task")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Delete a VTODO task by UID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "UID of the task to delete.",
                    },
                    "backend": {
                        "type": "string",
                        "description": "Name of the backend that owns the task.",
                    },
                },
                "required": ["uid", "backend"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "uid" not in args:
            raise RuntimeError("uid argument missing in arguments")
        if "backend" not in args:
            raise RuntimeError("backend argument missing in arguments")

        backend_name: str = args["backend"]
        backend = next((b for b in _backends if b.name == backend_name), None)
        if backend is None:
            raise RuntimeError(f"Backend '{backend_name}' not found")

        backend.delete_task(args["uid"])
        return [TextContent(type="text", text=f"Successfully deleted task {args['uid']}")]


ALL_HANDLERS: list[ToolHandler] = [
    ListCalendarsToolHandler(),
    ListEventsToolHandler(),
    CreateEventToolHandler(),
    UpdateEventToolHandler(),
    DeleteEventToolHandler(),
    GetFreeBusyToolHandler(),
    ListTasksToolHandler(),
    CreateTaskToolHandler(),
    UpdateTaskToolHandler(),
    DeleteTaskToolHandler(),
]

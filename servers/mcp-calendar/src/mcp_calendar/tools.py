from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
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
            description="Create a new calendar event on a specific backend.",
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
                        "description": "Start datetime as ISO 8601 string.",
                    },
                    "end": {
                        "type": "string",
                        "description": "End datetime as ISO 8601 string.",
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

        start = datetime.fromisoformat(args["start"])
        end = datetime.fromisoformat(args["end"])

        event = backend.create_event(
            summary=args["summary"],
            start=start,
            end=end,
            calendar_name=args.get("calendar_name"),
            description=args.get("description"),
            location=args.get("location"),
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
                        "description": "New start datetime as ISO 8601 string.",
                    },
                    "end": {
                        "type": "string",
                        "description": "New end datetime as ISO 8601 string.",
                    },
                    "description": {
                        "type": "string",
                        "description": "New event description.",
                    },
                    "location": {
                        "type": "string",
                        "description": "New event location.",
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

        start: datetime | None = datetime.fromisoformat(args["start"]) if "start" in args else None
        end: datetime | None = datetime.fromisoformat(args["end"]) if "end" in args else None

        event = backend.update_event(
            uid=args["uid"],
            summary=args.get("summary"),
            start=start,
            end=end,
            description=args.get("description"),
            location=args.get("location"),
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
                        "description": "Optional due date as ISO 8601 date string (YYYY-MM-DD).",
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

        due: date | None = date.fromisoformat(args["due"]) if "due" in args else None

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
                        "description": "New due date as ISO 8601 date string (YYYY-MM-DD).",
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

        due: date | None = date.fromisoformat(args["due"]) if "due" in args else None
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

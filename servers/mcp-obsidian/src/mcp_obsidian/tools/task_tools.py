from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal

from mcp.types import Tool
from pydantic import BaseModel

from mcp_obsidian.config import Config
from mcp_obsidian.tasks.collector import collect_all_tasks
from mcp_obsidian.tasks.mutator import (
    add_task_to_file,
    complete_task_in_file,
    set_task_date_in_file,
)


class GetTasksInput(BaseModel):
    context_tag: str | None = None
    group: Literal["priority", "waiting", "normal", "notag", "someday"] | None = None
    hide_future_scheduled: bool = True
    include_someday: bool = False
    include_waiting: bool = True
    project_tasks_only: bool = False
    exclude_projects: bool = False
    apply_sequencing: bool = True


class CompleteTaskInput(BaseModel):
    path: str
    line: int
    done_date: str | None = None


class SetTaskDateInput(BaseModel):
    path: str
    line: int
    date_type: Literal["due", "scheduled", "start", "created"]
    date: str | None = None


class AddTaskInput(BaseModel):
    path: str
    text: str
    tags: list[str] = []
    scheduled_date: str | None = None
    due_date: str | None = None
    start_date: str | None = None
    priority: Literal["highest", "high", "medium", "low", "lowest", ""] = ""
    stamp_created: bool = True
    append_under_heading: str | None = None


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="get_tasks",
            description=(
                "Collect and return all open tasks from the vault. "
                "Applies project sequencing (first task per section), excludes Utility folder, "
                "and groups tasks by priority/waiting/normal/notag/someday."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "context_tag": {
                        "type": "string",
                        "description": "Filter to tasks with this tag, e.g. '#context/pc'.",
                        "default": None,
                    },
                    "group": {
                        "type": "string",
                        "enum": ["priority", "waiting", "normal", "notag", "someday"],
                        "description": "Filter to a specific group.",
                        "default": None,
                    },
                    "hide_future_scheduled": {"type": "boolean", "default": True},
                    "include_someday": {"type": "boolean", "default": False},
                    "include_waiting": {"type": "boolean", "default": True},
                    "project_tasks_only": {"type": "boolean", "default": False},
                    "exclude_projects": {"type": "boolean", "default": False},
                    "apply_sequencing": {
                        "type": "boolean",
                        "default": True,
                        "description": "Apply GTD sequencing to #project notes.",
                    },
                },
            },
        ),
        Tool(
            name="complete_task",
            description="Mark an open task as done. Patches - [ ] → - [x] and appends ✅ date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {
                        "type": "integer",
                        "description": "1-indexed line number from get_tasks result.",
                    },
                    "done_date": {
                        "type": "string",
                        "description": "YYYY-MM-DD; defaults to today.",
                        "default": None,
                    },
                },
                "required": ["path", "line"],
            },
        ),
        Tool(
            name="set_task_date",
            description="Set, update, or remove a date emoji field (⏳📅🛫➕) on a task line.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "date_type": {
                        "type": "string",
                        "enum": ["due", "scheduled", "start", "created"],
                    },
                    "date": {
                        "type": "string",
                        "description": "YYYY-MM-DD; null removes the field.",
                        "default": None,
                    },
                },
                "required": ["path", "line", "date_type"],
            },
        ),
        Tool(
            name="add_task",
            description="Append a new task to a file with proper emoji metadata formatting.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "text": {
                        "type": "string",
                        "description": "Task description (no emoji needed).",
                    },
                    "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                    "scheduled_date": {"type": "string", "default": None},
                    "due_date": {"type": "string", "default": None},
                    "start_date": {"type": "string", "default": None},
                    "priority": {
                        "type": "string",
                        "enum": ["highest", "high", "medium", "low", "lowest", ""],
                        "default": "",
                    },
                    "stamp_created": {"type": "boolean", "default": True},
                    "append_under_heading": {
                        "type": "string",
                        "description": "Insert after the last task under this heading.",
                        "default": None,
                    },
                },
                "required": ["path", "text"],
            },
        ),
    ]


def get_handlers(config: Config) -> dict[str, Callable[..., Any]]:
    async def handle_get_tasks(arguments: dict[str, Any]) -> dict[str, Any]:
        args = GetTasksInput(**arguments)
        return await asyncio.to_thread(
            collect_all_tasks,
            config.vault_path,
            args.context_tag,
            args.group,
            args.hide_future_scheduled,
            args.include_someday,
            args.include_waiting,
            args.project_tasks_only,
            args.exclude_projects,
            args.apply_sequencing,
        )

    async def handle_complete_task(arguments: dict[str, Any]) -> dict[str, Any]:
        args = CompleteTaskInput(**arguments)
        return await asyncio.to_thread(
            complete_task_in_file, config.vault_path, args.path, args.line, args.done_date
        )

    async def handle_set_task_date(arguments: dict[str, Any]) -> dict[str, Any]:
        args = SetTaskDateInput(**arguments)
        return await asyncio.to_thread(
            set_task_date_in_file,
            config.vault_path,
            args.path,
            args.line,
            args.date_type,
            args.date,
        )

    async def handle_add_task(arguments: dict[str, Any]) -> dict[str, Any]:
        args = AddTaskInput(**arguments)
        return await asyncio.to_thread(
            add_task_to_file,
            config.vault_path,
            args.path,
            args.text,
            args.tags,
            args.scheduled_date,
            args.due_date,
            args.start_date,
            args.priority,
            args.stamp_created,
            args.append_under_heading,
        )

    return {
        "get_tasks": handle_get_tasks,
        "complete_task": handle_complete_task,
        "set_task_date": handle_set_task_date,
        "add_task": handle_add_task,
    }

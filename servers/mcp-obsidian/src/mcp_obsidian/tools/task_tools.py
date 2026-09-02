from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date
from typing import Any, Literal

from mcp.types import Tool
from pydantic import BaseModel, ConfigDict

from mcp_obsidian.config import Config
from mcp_obsidian.tasks.collector import collect_all_tasks
from mcp_obsidian.tasks.mutator import (
    add_task_to_file,
    complete_task_in_file,
    set_task_date_in_file,
)


class GetTasksInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[str] | None = None
    exclude_tags: list[str] | None = None
    priority: bool | None = None
    untagged: bool | None = None
    available_on: date | None = None
    project_tasks_only: bool = False
    exclude_projects: bool = False
    apply_sequencing: bool = True
    path: str | None = None


class CompleteTaskInput(BaseModel):
    path: str
    line: int
    done_date: str | None = None


class SetTaskDateInput(BaseModel):
    # Unknown keys are rejected rather than ignored: silently dropping a date a
    # caller asked for would lose it with no signal.
    model_config = ConfigDict(extra="forbid")

    path: str
    line: int
    date_type: Literal["scheduled", "created"]
    date: str | None = None


class AddTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    text: str
    tags: list[str] = []
    scheduled_date: str | None = None
    priority: bool = False
    stamp_created: bool = True
    append_under_heading: str | None = None


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="get_tasks",
            description=(
                "Collect and return all open tasks from the vault. Applies project "
                "sequencing (exactly one available next action per heading in a "
                "#project note), excludes the Utility folder, and returns a flat list "
                "where each task carries its facets: a priority flag and its tags."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Only tasks carrying ALL of these tags, e.g. "
                            "['#context/pc'] or ['#someday', '#context/pc']."
                        ),
                        "default": None,
                    },
                    "exclude_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Only tasks carrying NONE of these tags, e.g. "
                            "['#someday'] for an actionable list."
                        ),
                        "default": None,
                    },
                    "priority": {
                        "type": "boolean",
                        "description": (
                            "Filter by the 🔼 priority facet, which a task may also "
                            "inherit from its project note. Omit to ignore it."
                        ),
                        "default": None,
                    },
                    "untagged": {
                        "type": "boolean",
                        "description": "Filter to tasks with no tags at all (unprocessed).",
                        "default": None,
                    },
                    "available_on": {
                        # null is meaningful here: it disables the availability test.
                        "type": ["string", "null"],
                        "description": (
                            "YYYY-MM-DD. Only return tasks actionable on this date; "
                            "a task deferred with ⏳ to a later date is not, and in a "
                            "project section silences that section entirely. Omit for "
                            "today. Pass null to ignore availability."
                        ),
                        "default": None,
                    },
                    "project_tasks_only": {"type": "boolean", "default": False},
                    "exclude_projects": {"type": "boolean", "default": False},
                    "apply_sequencing": {
                        "type": "boolean",
                        "default": True,
                        "description": "Apply GTD sequencing to #project notes.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Restrict to a single note or folder prefix, "
                            "e.g. 'Projects/MyProject.md' or 'Projects/'."
                        ),
                        "default": None,
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
            description=(
                "Set, update, or remove a date on a task line. Only the two markers "
                "this workflow writes are settable: ⏳ (scheduled) and ➕ (created)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "date_type": {
                        "type": "string",
                        "enum": ["scheduled", "created"],
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
                    "scheduled_date": {
                        "type": "string",
                        "description": (
                            "YYYY-MM-DD. Defer the task until this date: it is not "
                            "actionable before then and will not appear in task "
                            "queries until it arrives. Not a deadline -- a real "
                            "deadline belongs in the calendar, not here."
                        ),
                        "default": None,
                    },
                    "priority": {
                        "type": "boolean",
                        "description": "Mark the task as priority (writes 🔼).",
                        "default": False,
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
        # Omitted means today; an explicit null disables the availability test.
        available_on = (
            args.available_on if "available_on" in args.model_fields_set else date.today()
        )
        return await asyncio.to_thread(
            collect_all_tasks,
            config.vault_path,
            tags=args.tags,
            exclude_tags=args.exclude_tags,
            priority=args.priority,
            untagged=args.untagged,
            available_on=available_on,
            project_tasks_only=args.project_tasks_only,
            exclude_projects=args.exclude_projects,
            apply_sequencing=args.apply_sequencing,
            path=args.path,
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

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import jsonschema  # type: ignore[import-untyped]
from mcp.types import Tool

from mcp_obsidian.config import Config

# Read-only tools never mutate any path; always safe to parallelise.
_READ_ONLY_TOOLS = frozenset(
    {
        "read_note",
        "read_multiple_notes",
        "get_frontmatter",
        "list_directory",
        "get_vault_stats",
        "search_notes",
        "list_all_tags",
        "get_backlinks",
        "get_outgoing_links",
    }
)


def _extract_path(arguments: dict[str, Any]) -> str | None:
    """Return a grouping key for the invocation (path arg or None for read-only)."""
    return arguments.get("path") or arguments.get("source")


def _validate_invocations(
    invocations: list[dict[str, Any]],
    handlers: dict[str, Callable[..., Any]],
    tools_by_name: dict[str, Tool],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for i, inv in enumerate(invocations):
        tool_name = inv.get("tool", "")
        arguments = inv.get("arguments", {})
        if tool_name not in handlers or tool_name not in tools_by_name:
            errors.append(
                {
                    "index": i,
                    "tool": tool_name,
                    "error": f"Unknown tool: {tool_name!r}",
                }
            )
            continue
        schema = tools_by_name[tool_name].inputSchema
        try:
            jsonschema.validate(instance=arguments, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append({"index": i, "tool": tool_name, "error": exc.message})
    return errors


async def execute_batch(
    invocations: list[dict[str, Any]],
    handlers: dict[str, Callable[..., Any]],
    tools_by_name: dict[str, Tool],
) -> dict[str, Any]:
    errors = _validate_invocations(invocations, handlers, tools_by_name)
    if errors:
        return {"status": "validation_failed", "errors": errors, "results": []}

    # Group by path; read-only tools and no-path tools use a unique virtual key.
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for i, inv in enumerate(invocations):
        tool_name = inv["tool"]
        if tool_name in _READ_ONLY_TOOLS:
            key = f"__readonly_{i}"
        else:
            path = _extract_path(inv.get("arguments", {}))
            key = path if path else f"__nopath_{i}"
        groups.setdefault(key, []).append((i, inv))

    results: list[dict[str, Any]] = [None] * len(invocations)  # type: ignore[list-item]

    async def run_group(group: list[tuple[int, dict[str, Any]]]) -> None:
        for idx, inv in group:
            tool_name = inv["tool"]
            arguments = inv.get("arguments", {})
            try:
                result = await handlers[tool_name](arguments)
                results[idx] = {
                    "index": idx,
                    "tool": tool_name,
                    "result": result,
                    "error": None,
                }
            except Exception as exc:  # noqa: BLE001
                results[idx] = {
                    "index": idx,
                    "tool": tool_name,
                    "result": None,
                    "error": str(exc),
                }

    await asyncio.gather(*[run_group(group) for group in groups.values()])

    return {"status": "ok", "results": results}


def get_tool() -> Tool:
    return Tool(
        name="batch_tool",
        description=(
            "Invoke multiple tools in a single call. "
            "Operations on distinct paths are executed in parallel; "
            "operations on the same path are executed sequentially in submission order. "
            "All invocations are validated before any are executed — "
            "if any fail validation, no side effects occur."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "invocations": {
                    "type": "array",
                    "description": "List of tool invocations to execute.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {
                                "type": "string",
                                "description": "Name of the tool to invoke.",
                            },
                            "arguments": {
                                "type": "object",
                                "description": "Arguments for that tool.",
                            },
                        },
                        "required": ["tool", "arguments"],
                    },
                }
            },
            "required": ["invocations"],
        },
    )


def get_handler(
    handlers: dict[str, Callable[..., Any]],
    tools_by_name: dict[str, Tool],
) -> Callable[..., Any]:
    async def handle_batch(arguments: dict[str, Any]) -> dict[str, Any]:
        invocations = arguments.get("invocations", [])
        # Prevent nesting batch_tool within itself.
        safe_handlers = {k: v for k, v in handlers.items() if k != "batch_tool"}
        safe_tools = {k: v for k, v in tools_by_name.items() if k != "batch_tool"}
        return await execute_batch(invocations, safe_handlers, safe_tools)

    return handle_batch


def register(
    config: Config,
    all_tools: list[Tool],
    all_handlers: dict[str, Any],
) -> None:
    tools_by_name = {t.name: t for t in all_tools}
    handler = get_handler(all_handlers.copy(), tools_by_name)
    tool = get_tool()
    all_tools.append(tool)
    all_handlers["batch_tool"] = handler

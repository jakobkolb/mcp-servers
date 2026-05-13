from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_obsidian.config import Config
from mcp_obsidian.vault.search import list_all_tags, search_notes


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="search_notes",
            description=(
                "Full-text regex search across vault .md files. "
                "Falls back to literal match when query is not valid regex."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (regex or literal string)."},
                    "search_content": {"type": "boolean", "default": True},
                    "search_frontmatter": {"type": "boolean", "default": False},
                    "case_sensitive": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "default": 5, "description": "Max results (capped at SEARCH_LIMIT_MAX)."},
                    "path_filter": {"type": "string", "description": "Restrict to notes under this folder prefix.", "default": None},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_all_tags",
            description="Return all tags in the vault with occurrence counts. Sorted by count descending.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def get_handlers(config: Config) -> dict[str, Callable[..., Any]]:
    async def handle_search_notes(arguments: dict[str, Any]) -> dict[str, Any]:
        return search_notes(
            vault_root=config.vault_path,
            query=arguments["query"],
            search_content=arguments.get("search_content", True),
            search_frontmatter=arguments.get("search_frontmatter", False),
            case_sensitive=arguments.get("case_sensitive", False),
            limit=arguments.get("limit", 5),
            path_filter=arguments.get("path_filter"),
            search_limit_max=config.search_limit_max,
        )

    async def handle_list_all_tags(arguments: dict[str, Any]) -> dict[str, Any]:
        return list_all_tags(config.vault_path)

    return {
        "search_notes": handle_search_notes,
        "list_all_tags": handle_list_all_tags,
    }

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.types import Tool
from pydantic import BaseModel

from mcp_obsidian.config import Config
from mcp_obsidian.vault.search import list_all_tags, search_notes


class SearchNotesInput(BaseModel):
    query: str
    search_content: bool = True
    search_frontmatter: bool = False
    case_sensitive: bool = False
    limit: int = 5
    path_filter: str | None = None
    include_frontmatter: bool = False
    tag_filter: str | None = None
    frontmatter_filter: dict[str, Any] | None = None


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
                    "query": {
                        "type": "string",
                        "description": "Search query (regex or literal string).",
                    },
                    "search_content": {"type": "boolean", "default": True},
                    "search_frontmatter": {"type": "boolean", "default": False},
                    "case_sensitive": {"type": "boolean", "default": False},
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "description": "Max results (capped at SEARCH_LIMIT_MAX).",
                    },
                    "path_filter": {
                        "type": "string",
                        "description": "Restrict to notes under this folder prefix.",
                        "default": None,
                    },
                    "include_frontmatter": {
                        "type": "boolean",
                        "default": False,
                        "description": "When true, include parsed frontmatter dict in each result.",
                    },
                    "tag_filter": {
                        "type": "string",
                        "description": (
                            "Return only notes carrying this tag "
                            "(frontmatter or inline). E.g. '#project'."
                        ),
                        "default": None,
                    },
                    "frontmatter_filter": {
                        "type": "object",
                        "description": (
                            "Return only notes whose frontmatter contains all "
                            "key/value pairs (exact equality). "
                            'E.g. {"type": "project", "status": "active"}.'
                        ),
                        "default": None,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_all_tags",
            description="Return all vault tags with occurrence counts, sorted by count descending.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def get_handlers(config: Config) -> dict[str, Callable[..., Any]]:
    async def handle_search_notes(arguments: dict[str, Any]) -> dict[str, Any]:
        args = SearchNotesInput(**arguments)
        return search_notes(
            vault_root=config.vault_path,
            query=args.query,
            search_content=args.search_content,
            search_frontmatter=args.search_frontmatter,
            case_sensitive=args.case_sensitive,
            limit=args.limit,
            path_filter=args.path_filter,
            search_limit_max=config.search_limit_max,
            include_frontmatter=args.include_frontmatter,
            tag_filter=args.tag_filter,
            frontmatter_filter=args.frontmatter_filter,
        )

    async def handle_list_all_tags(arguments: dict[str, Any]) -> dict[str, Any]:
        return list_all_tags(config.vault_path)

    return {
        "search_notes": handle_search_notes,
        "list_all_tags": handle_list_all_tags,
    }

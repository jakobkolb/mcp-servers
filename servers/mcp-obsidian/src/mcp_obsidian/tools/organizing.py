from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.types import Tool
from pydantic import BaseModel

from mcp_obsidian.config import Config
from mcp_obsidian.errors import NoteNotFoundError
from mcp_obsidian.vault.links import get_backlinks, move_file, move_note_with_link_rewrite
from mcp_obsidian.vault.path import resolve


class MoveNoteInput(BaseModel):
    source: str
    destination: str
    create_dirs: bool = True


class MoveFileInput(BaseModel):
    source: str
    destination: str
    create_dirs: bool = True


class DeleteNoteInput(BaseModel):
    path: str
    confirm: bool = False


class GetBacklinksInput(BaseModel):
    path: str


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="move_note",
            description="Move or rename a .md note, rewriting [[wiki-links]] that reference it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Vault-relative current path."},
                    "destination": {"type": "string", "description": "Vault-relative target path."},
                    "create_dirs": {"type": "boolean", "default": True},
                },
                "required": ["source", "destination"],
            },
        ),
        Tool(
            name="move_file",
            description=(
                "Move any file without rewriting wiki-links. Binary-safe. "
                "Use move_note for .md files unless link rewriting is unwanted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                    "create_dirs": {"type": "boolean", "default": True},
                },
                "required": ["source", "destination"],
            },
        ),
        Tool(
            name="delete_note",
            description="Delete a markdown note. Irreversible. Requires confirm=true to proceed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": "Must be true to actually delete.",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="get_backlinks",
            description=(
                "Return all notes that contain a [[wiki-link]] pointing to the given note. "
                "Useful for knowledge graph navigation and finding related notes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Vault-relative path of the note to find backlinks for.",
                    },
                },
                "required": ["path"],
            },
        ),
    ]


def get_handlers(config: Config) -> dict[str, Callable[..., Any]]:
    async def handle_move_note(arguments: dict[str, Any]) -> dict[str, Any]:
        args = MoveNoteInput(**arguments)
        return move_note_with_link_rewrite(
            config.vault_path, args.source, args.destination, args.create_dirs
        )

    async def handle_move_file(arguments: dict[str, Any]) -> dict[str, Any]:
        args = MoveFileInput(**arguments)
        return move_file(config.vault_path, args.source, args.destination, args.create_dirs)

    async def handle_delete_note(arguments: dict[str, Any]) -> dict[str, Any]:
        args = DeleteNoteInput(**arguments)
        if not args.confirm:
            return {
                "path": args.path,
                "deleted": False,
                "message": f"Set confirm=true to proceed with deletion of {args.path!r}.",
            }
        abs_path = resolve(config.vault_path, args.path)
        if not abs_path.exists():
            raise NoteNotFoundError(f"Note not found: {args.path!r}")
        abs_path.unlink()
        return {"path": args.path, "deleted": True, "message": "Deleted."}

    async def handle_get_backlinks(arguments: dict[str, Any]) -> dict[str, Any]:
        args = GetBacklinksInput(**arguments)
        return get_backlinks(config.vault_path, args.path)

    return {
        "move_note": handle_move_note,
        "move_file": handle_move_file,
        "delete_note": handle_delete_note,
        "get_backlinks": handle_get_backlinks,
    }

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, field_validator

from mcp_obsidian.config import Config
from mcp_obsidian.errors import NotANoteError, NoteNotFoundError, VaultError, VaultPathError
from mcp_obsidian.vault.io import Note, read_note


class ReadNoteInput(BaseModel):
    path: str
    pretty_print: bool = False

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("path must not be empty")
        return value


def _note_to_dict(note: Note, pretty_print: bool) -> dict[str, Any]:
    content = note.content
    if pretty_print and note.frontmatter:
        frontmatter_lines = "\n".join(f"{key}: {value}" for key, value in note.frontmatter.items())
        content = f"{frontmatter_lines}\n\n{note.content}"

    return {
        "path": note.path,
        "frontmatter": note.frontmatter,
        "content": content,
        "raw": note.raw,
        "mtime": note.mtime,
        "size": note.size,
    }


def _error_result(code: str, message: str) -> CallToolResult:
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text=f"{code}: {message}")],
    )


def register_reading_tools(server: Server, config: Config) -> None:
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        if name != "read_note":
            return _error_result("NOT_IMPLEMENTED", f"Tool {name!r} is not implemented.")

        try:
            args = ReadNoteInput(**arguments)
        except Exception as exc:
            return _error_result("INVALID_ARGUMENTS", str(exc))

        try:
            note = read_note(config.vault_path, args.path)
        except VaultPathError as exc:
            return _error_result("INVALID_PATH", str(exc))
        except NoteNotFoundError as exc:
            return _error_result("NOT_FOUND", str(exc))
        except NotANoteError as exc:
            return _error_result("NOT_A_NOTE", str(exc))
        except VaultError as exc:
            return _error_result("VAULT_ERROR", str(exc))

        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(_note_to_dict(note, args.pretty_print), ensure_ascii=False),
                )
            ]
        )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="read_note",
                description=(
                    "Read a single markdown note from the vault. Returns frontmatter, body "
                    "content, raw content, and file metadata."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Vault-relative path to the note.",
                        },
                        "pretty_print": {
                            "type": "boolean",
                            "description": "Render frontmatter as key/value lines in content.",
                            "default": False,
                        },
                    },
                    "required": ["path"],
                },
            )
        ]

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.types import Tool
from pydantic import BaseModel, field_validator

from mcp_obsidian.config import Config
from mcp_obsidian.errors import BatchTooLargeError
from mcp_obsidian.vault.io import Note, read_note
from mcp_obsidian.vault.path import resolve


class ReadNoteInput(BaseModel):
    path: str
    pretty_print: bool = False

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("path must not be empty")
        return v


class ReadMultipleNotesInput(BaseModel):
    paths: list[str]
    include_content: bool = True
    include_frontmatter: bool = True


class GetFrontmatterInput(BaseModel):
    path: str


class GetNotesInfoInput(BaseModel):
    paths: list[str]


class ListDirectoryInput(BaseModel):
    path: str = ""
    recursive: bool = False


def _note_to_dict(note: Note, pretty_print: bool) -> dict[str, Any]:
    content = note.content
    if pretty_print and note.frontmatter:
        fm_lines = "\n".join(f"{k}: {v}" for k, v in note.frontmatter.items())
        content = f"{fm_lines}\n\n{note.content}"
    return {
        "path": note.path,
        "frontmatter": note.frontmatter,
        "content": content,
        "raw": note.raw,
        "mtime": note.mtime,
        "size": note.size,
    }


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="read_note",
            description="Read a markdown note. Returns frontmatter, body, raw content, metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Vault-relative path to the note (must end in .md).",
                    },
                    "pretty_print": {
                        "type": "boolean",
                        "description": "Render frontmatter as key/value lines in content.",
                        "default": False,
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="read_multiple_notes",
            description=(
                "Batch read up to MAX_BATCH_READ notes concurrently. "
                "Per-note failures are in the error field, not raised."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Vault-relative paths (max MAX_BATCH_READ).",
                    },
                    "include_content": {"type": "boolean", "default": True},
                    "include_frontmatter": {"type": "boolean", "default": True},
                },
                "required": ["paths"],
            },
        ),
        Tool(
            name="get_frontmatter",
            description=(
                "Return only the YAML frontmatter (~5% cost of read_note). Use for filter passes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Vault-relative path."},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="get_notes_info",
            description=(
                "Return filesystem metadata (mtime, ctime, size, is_note) without reading content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["paths"],
            },
        ),
        Tool(
            name="list_directory",
            description=(
                "List files and subdirectories in a vault folder. "
                "Cheaper than search_notes when the path is known."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Vault-relative folder path. Empty string = vault root.",
                        "default": "",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "If true, return the full subtree.",
                        "default": False,
                    },
                },
            },
        ),
    ]


def get_handlers(config: Config) -> dict[str, Callable[..., Any]]:
    async def handle_read_note(arguments: dict[str, Any]) -> dict[str, Any]:
        args = ReadNoteInput(**arguments)
        note = await asyncio.to_thread(read_note, config.vault_path, args.path)
        return _note_to_dict(note, args.pretty_print)

    async def handle_read_multiple_notes(arguments: dict[str, Any]) -> dict[str, Any]:
        args = ReadMultipleNotesInput(**arguments)
        if len(args.paths) > config.max_batch_read:
            raise BatchTooLargeError(
                f"Too many paths: {len(args.paths)} > {config.max_batch_read} (MAX_BATCH_READ)"
            )

        async def _read_one(path: str) -> dict[str, Any]:
            try:
                note = await asyncio.to_thread(read_note, config.vault_path, path)
                return {
                    "path": note.path,
                    "frontmatter": note.frontmatter if args.include_frontmatter else None,
                    "content": note.content if args.include_content else None,
                    "mtime": note.mtime,
                    "size": note.size,
                    "error": None,
                }
            except Exception as e:
                return {
                    "path": path,
                    "frontmatter": None,
                    "content": None,
                    "mtime": None,
                    "size": None,
                    "error": str(e),
                }

        notes = list(await asyncio.gather(*[_read_one(p) for p in args.paths]))
        return {"notes": notes, "errors": sum(1 for n in notes if n["error"] is not None)}

    async def handle_get_frontmatter(arguments: dict[str, Any]) -> dict[str, Any]:
        args = GetFrontmatterInput(**arguments)
        note = await asyncio.to_thread(read_note, config.vault_path, args.path)
        return {"path": args.path, "frontmatter": note.frontmatter}

    async def handle_get_notes_info(arguments: dict[str, Any]) -> dict[str, Any]:
        args = GetNotesInfoInput(**arguments)

        def _get_one(path: str) -> dict[str, Any]:
            try:
                abs_path = resolve(config.vault_path, path)
                if not abs_path.exists():
                    return {
                        "path": path,
                        "exists": False,
                        "mtime": None,
                        "ctime": None,
                        "size": None,
                        "is_note": False,
                    }
                stat = abs_path.stat()
                return {
                    "path": path,
                    "exists": True,
                    "mtime": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    "ctime": datetime.fromtimestamp(stat.st_ctime, tz=UTC).isoformat(),
                    "size": stat.st_size,
                    "is_note": abs_path.suffix.lower() == ".md",
                }
            except Exception:
                return {
                    "path": path,
                    "exists": False,
                    "mtime": None,
                    "ctime": None,
                    "size": None,
                    "is_note": False,
                }

        infos = list(await asyncio.gather(*[asyncio.to_thread(_get_one, p) for p in args.paths]))
        return {"notes": infos}

    async def handle_list_directory(arguments: dict[str, Any]) -> dict[str, Any]:
        args = ListDirectoryInput(**arguments)
        vault_root = Path(config.vault_path)

        dir_abs = resolve(config.vault_path, args.path) if args.path else vault_root

        files: list[dict[str, Any]] = []
        directories: list[dict[str, str]] = []

        entries = sorted(dir_abs.rglob("*") if args.recursive else dir_abs.iterdir())
        for entry in entries:
            if entry.name.startswith("."):
                continue
            rel = str(entry.relative_to(vault_root))
            if entry.is_dir():
                directories.append({"name": entry.name, "path": rel})
            elif entry.is_file():
                try:
                    stat = entry.stat()
                    files.append(
                        {
                            "name": entry.name,
                            "path": rel,
                            "is_note": entry.suffix.lower() == ".md",
                            "size": stat.st_size,
                            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                        }
                    )
                except OSError:
                    continue

        return {
            "path": args.path,
            "files": files,
            "directories": directories,
            "total_files": len(files),
            "total_dirs": len(directories),
        }

    return {
        "read_note": handle_read_note,
        "read_multiple_notes": handle_read_multiple_notes,
        "get_frontmatter": handle_get_frontmatter,
        "get_notes_info": handle_get_notes_info,
        "list_directory": handle_list_directory,
    }

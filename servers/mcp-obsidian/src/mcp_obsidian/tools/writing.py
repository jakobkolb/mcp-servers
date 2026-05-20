from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from mcp.types import Tool
from pydantic import BaseModel

from mcp_obsidian.config import Config
from mcp_obsidian.errors import NoteAlreadyExistsError
from mcp_obsidian.vault.frontmatter import build_note_content
from mcp_obsidian.vault.io import atomic_write, patch_note, read_note
from mcp_obsidian.vault.path import resolve


class WriteNoteInput(BaseModel):
    path: str
    content: str
    mode: Literal["overwrite", "append", "prepend", "create"] = "overwrite"
    create_dirs: bool = True


class PatchNoteInput(BaseModel):
    path: str
    old_string: str
    new_string: str
    replace_all: bool = False


class UpdateFrontmatterInput(BaseModel):
    path: str
    frontmatter: dict[str, Any]
    merge: bool = True


class ManageTagsInput(BaseModel):
    path: str
    operation: Literal["add", "remove", "list"]
    tags: list[str] = []


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="write_note",
            description="Create or write a note (overwrite/append/prepend). All writes are atomic.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append", "prepend", "create"],
                        "default": "overwrite",
                        "description": (
                            "'create' fails with ALREADY_EXISTS if the note already exists."
                        ),
                    },
                    "create_dirs": {"type": "boolean", "default": True},
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="patch_note",
            description=(
                "Targeted find-and-replace within a note. Works on bytes to handle emoji. "
                "Raises PATCH_NO_MATCH if not found, PATCH_AMBIGUOUS if multiple matches."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {
                        "type": "string",
                        "description": "Must match exactly (including whitespace).",
                    },
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean", "default": False},
                },
                "required": ["path", "old_string", "new_string"],
            },
        ),
        Tool(
            name="update_frontmatter",
            description="Merge or replace frontmatter fields on a note, preserving the body.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "frontmatter": {"type": "object", "description": "Fields to set/update."},
                    "merge": {
                        "type": "boolean",
                        "default": True,
                        "description": "True: merge with existing. False: replace entirely.",
                    },
                },
                "required": ["path", "frontmatter"],
            },
        ),
        Tool(
            name="manage_tags",
            description="Add, remove, or list tags in the frontmatter tags field of a note.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "operation": {"type": "string", "enum": ["add", "remove", "list"]},
                    "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                },
                "required": ["path", "operation"],
            },
        ),
    ]


def get_handlers(config: Config) -> dict[str, Callable[..., Any]]:
    async def handle_write_note(arguments: dict[str, Any]) -> dict[str, Any]:
        args = WriteNoteInput(**arguments)
        abs_path = resolve(config.vault_path, args.path)
        created = not abs_path.exists()

        if args.mode == "create":
            if abs_path.exists():
                raise NoteAlreadyExistsError(f"Note already exists: {args.path}")
            content_bytes = args.content.encode("utf-8")
        elif args.mode == "overwrite":
            content_bytes = args.content.encode("utf-8")
        elif args.mode == "append":
            existing = abs_path.read_bytes() if abs_path.exists() else b""
            content_bytes = existing + args.content.encode("utf-8")
        else:  # prepend
            existing = abs_path.read_bytes() if abs_path.exists() else b""
            content_bytes = args.content.encode("utf-8") + existing

        if args.create_dirs:
            abs_path.parent.mkdir(parents=True, exist_ok=True)

        atomic_write(abs_path, content_bytes)
        return {
            "path": args.path,
            "mode": args.mode,
            "bytes_written": len(content_bytes),
            "created": created,
        }

    async def handle_patch_note(arguments: dict[str, Any]) -> dict[str, Any]:
        args = PatchNoteInput(**arguments)
        return patch_note(
            config.vault_path, args.path, args.old_string, args.new_string, args.replace_all
        )

    async def handle_update_frontmatter(arguments: dict[str, Any]) -> dict[str, Any]:
        args = UpdateFrontmatterInput(**arguments)
        note = read_note(config.vault_path, args.path)
        fields_before = set(note.frontmatter.keys())

        new_fm = dict(note.frontmatter) if args.merge else {}
        new_fm.update(args.frontmatter)

        fields_after = set(new_fm.keys())
        fields_added = sorted(fields_after - fields_before)
        fields_updated = sorted(k for k in args.frontmatter if k not in fields_added)

        abs_path = resolve(config.vault_path, args.path)
        atomic_write(abs_path, build_note_content(new_fm, note.content).encode("utf-8"))

        return {
            "path": args.path,
            "fields_updated": fields_updated,
            "fields_added": fields_added,
            "frontmatter_after": new_fm,
        }

    async def handle_manage_tags(arguments: dict[str, Any]) -> dict[str, Any]:
        args = ManageTagsInput(**arguments)
        note = read_note(config.vault_path, args.path)

        raw = note.frontmatter.get("tags", [])
        if isinstance(raw, str):
            raw = [raw]
        tags_before = [t.lstrip("#") for t in raw]

        if args.operation == "list":
            return {
                "path": args.path,
                "operation": "list",
                "tags_before": tags_before,
                "tags_after": None,
                "tags_added": [],
                "tags_removed": [],
            }

        incoming = [t.lstrip("#") for t in args.tags]
        existing_lower = {t.lower(): t for t in tags_before}

        if args.operation == "add":
            result_tags = list(tags_before)
            added = []
            for tag in incoming:
                if tag.lower() not in existing_lower:
                    result_tags.append(tag)
                    added.append(tag)
            removed: list[str] = []
        else:  # remove
            remove_lower = {t.lower() for t in incoming}
            result_tags = [t for t in tags_before if t.lower() not in remove_lower]
            removed = [t for t in incoming if t.lower() in existing_lower]
            added = []

        abs_path = resolve(config.vault_path, args.path)
        new_fm = dict(note.frontmatter)
        new_fm["tags"] = result_tags
        atomic_write(abs_path, build_note_content(new_fm, note.content).encode("utf-8"))

        return {
            "path": args.path,
            "operation": args.operation,
            "tags_before": tags_before,
            "tags_after": result_tags,
            "tags_added": added,
            "tags_removed": removed,
        }

    return {
        "write_note": handle_write_note,
        "patch_note": handle_patch_note,
        "update_frontmatter": handle_update_frontmatter,
        "manage_tags": handle_manage_tags,
    }

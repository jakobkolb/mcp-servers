from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mcp_obsidian.errors import NotANoteError, NoteNotFoundError
from mcp_obsidian.vault import frontmatter as frontmatter_mod
from mcp_obsidian.vault import path as vault_path


@dataclass(frozen=True)
class Note:
    path: str
    frontmatter: dict[str, Any]
    content: str
    raw: str
    mtime: str
    size: int


def read_note(vault_root: str, relative: str) -> Note:
    """Read a single markdown note from the vault."""
    absolute = vault_path.resolve(vault_root, relative)

    if not absolute.exists():
        raise NoteNotFoundError(f"Note not found: {relative!r}")

    if not absolute.is_file() or absolute.suffix.lower() != ".md":
        raise NotANoteError(f"Path is not a markdown note: {relative!r}")

    raw_bytes = absolute.read_bytes()
    raw = raw_bytes.decode("utf-8", errors="replace")
    metadata, body = frontmatter_mod.parse(raw)
    stat = absolute.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()

    return Note(
        path=relative,
        frontmatter=metadata,
        content=body,
        raw=raw,
        mtime=mtime,
        size=stat.st_size,
    )

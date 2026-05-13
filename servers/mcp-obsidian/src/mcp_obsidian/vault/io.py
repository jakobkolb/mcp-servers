from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp_obsidian.errors import (
    NotANoteError,
    NoteNotFoundError,
    PatchAmbiguousError,
    PatchNoMatchError,
    TaskStateError,
)
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


def atomic_write(path: Path, content: bytes) -> None:
    """Write content atomically using a temp file + os.replace."""
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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


def patch_note(
    vault_root: str,
    relative: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    """Targeted find-and-replace. Works on bytes to handle emoji paths and content."""
    abs_path = vault_path.resolve(vault_root, relative)
    content_bytes = abs_path.read_bytes()
    old_bytes = old_string.encode("utf-8")
    new_bytes = new_string.encode("utf-8")
    count = content_bytes.count(old_bytes)

    if count == 0:
        raise PatchNoMatchError(
            f"patch_note: old_string not found in {relative!r}. Re-read the note and retry."
        )
    if count > 1 and not replace_all:
        raise PatchAmbiguousError(
            f"patch_note: old_string matches {count} times in {relative!r}. "
            "Extend with more context or set replace_all=True."
        )

    if replace_all:
        result_bytes = content_bytes.replace(old_bytes, new_bytes)
        replacements = count
    else:
        result_bytes = content_bytes.replace(old_bytes, new_bytes, 1)
        replacements = 1

    atomic_write(abs_path, result_bytes)
    return {
        "path": relative,
        "replacements": replacements,
        "old_string_length": len(old_bytes),
        "new_string_length": len(new_bytes),
    }


def patch_line(
    vault_root: str,
    relative: str,
    line: int,
    transform: Callable[[str], str],
) -> str:
    """Read file, apply transform() to line `line` (1-indexed), write back atomically."""
    abs_path = vault_path.resolve(vault_root, relative)
    content = abs_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)

    if line < 1 or line > len(lines):
        raise TaskStateError(f"Line {line} out of range (file has {len(lines)} lines)")

    idx = line - 1
    lines[idx] = transform(lines[idx])
    new_content = "".join(lines)
    atomic_write(abs_path, new_content.encode("utf-8"))
    return lines[idx].rstrip("\n")

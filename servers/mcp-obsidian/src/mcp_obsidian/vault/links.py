from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from mcp_obsidian.vault.io import atomic_write
from mcp_obsidian.vault.path import resolve


def move_note_with_link_rewrite(
    vault_root: str,
    source: str,
    destination: str,
    create_dirs: bool = True,
) -> dict[str, Any]:
    """Move a .md note and rewrite all [[wiki-links]] that reference it."""
    vault = Path(vault_root)
    src_abs = resolve(vault_root, source)
    dst_abs = resolve(vault_root, destination)

    old_title = src_abs.stem
    new_title = dst_abs.stem

    if create_dirs:
        dst_abs.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(src_abs), str(dst_abs))

    if old_title == new_title:
        return {
            "source": source,
            "destination": destination,
            "links_rewritten": 0,
            "files_scanned": 0,
        }

    escaped = re.escape(old_title)
    link_re = re.compile(r"\[\[" + escaped + r"(\|[^\]]+|#[^\]]+(?:\|[^\]]+)?)?\]\]")

    def replace_link(m: re.Match) -> str:  # type: ignore[type-arg]
        suffix = m.group(1) or ""
        return f"[[{new_title}{suffix}]]"

    files_scanned = 0
    links_rewritten = 0

    for md_file in vault.rglob("*.md"):
        files_scanned += 1
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            new_content, n = link_re.subn(replace_link, content)
            if n > 0:
                atomic_write(md_file, new_content.encode("utf-8"))
                links_rewritten += n
        except OSError:
            continue

    return {
        "source": source,
        "destination": destination,
        "links_rewritten": links_rewritten,
        "files_scanned": files_scanned,
    }


def move_file(
    vault_root: str,
    source: str,
    destination: str,
    create_dirs: bool = True,
) -> dict[str, Any]:
    """Move any file without rewriting wiki-links. Binary-safe."""
    src_abs = resolve(vault_root, source)
    dst_abs = resolve(vault_root, destination)

    if create_dirs:
        dst_abs.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(src_abs), str(dst_abs))
    return {"source": source, "destination": destination}

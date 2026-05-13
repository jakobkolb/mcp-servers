from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.types import Tool

from mcp_obsidian.config import Config


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="get_vault_stats",
            description="Return aggregate statistics about the vault: note/file/dir counts, total size, and recently modified notes.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def get_handlers(config: Config) -> dict[str, Callable[..., Any]]:
    async def handle_get_vault_stats(arguments: dict[str, Any]) -> dict[str, Any]:
        vault = Path(config.vault_path)
        total_notes = 0
        total_files = 0
        total_dirs = 0
        total_size = 0
        recently_modified: list[dict[str, Any]] = []

        for entry in vault.rglob("*"):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                total_dirs += 1
            elif entry.is_file():
                total_files += 1
                try:
                    stat = entry.stat()
                    total_size += stat.st_size
                    rel = str(entry.relative_to(vault))
                    if entry.suffix.lower() == ".md":
                        total_notes += 1
                        recently_modified.append(
                            {
                                "path": rel,
                                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                                "_mtime_raw": stat.st_mtime,
                            }
                        )
                except OSError:
                    continue

        recently_modified.sort(key=lambda x: x["_mtime_raw"], reverse=True)
        top10 = [{"path": e["path"], "mtime": e["mtime"]} for e in recently_modified[:10]]

        return {
            "total_notes": total_notes,
            "total_files": total_files,
            "total_dirs": total_dirs,
            "total_size_bytes": total_size,
            "recently_modified": top10,
            "vault_path": config.vault_path,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

    return {"get_vault_stats": handle_get_vault_stats}

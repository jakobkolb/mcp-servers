from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from mcp_obsidian.errors import TaskStateError
from mcp_obsidian.vault.io import atomic_write, patch_line
from mcp_obsidian.vault.path import resolve

DATE_EMOJI = {
    "due": "📅",
    "scheduled": "⏳",
    "start": "🛫",
    "created": "➕",
}

DATE_PATTERN: dict[str, re.Pattern[str]] = {
    "due": re.compile(r"📅\s?(\d{4}-\d{2}-\d{2})"),
    "scheduled": re.compile(r"⏳\s?(\d{4}-\d{2}-\d{2})"),
    "start": re.compile(r"🛫\s?(\d{4}-\d{2}-\d{2})"),
    "created": re.compile(r"➕\s?(\d{4}-\d{2}-\d{2})"),
}

PRIORITY_EMOJI = {
    "highest": "🔺",
    "high": "⏫",
    "medium": "🔼",
    "low": "🔽",
    "lowest": "⏬",
    "": "",
}


def complete_task_in_file(
    vault_root: str,
    relative: str,
    line: int,
    done_date: str | None = None,
) -> dict[str, Any]:
    done_str = done_date or date.today().isoformat()

    abs_path = resolve(vault_root, relative)
    content = abs_path.read_text(encoding="utf-8", errors="replace")
    raw_lines = content.splitlines(keepends=True)

    if line < 1 or line > len(raw_lines):
        raise TaskStateError(f"Line {line} out of range (file has {len(raw_lines)} lines)")

    original = raw_lines[line - 1].rstrip("\n")
    if "- [ ]" not in original:
        raise TaskStateError(
            f"Line {line} does not contain an open task marker. Got: {original!r}"
        )

    task_text = original.replace("- [ ]", "", 1).strip()

    def transform(raw_line: str) -> str:
        updated = raw_line.rstrip("\n").replace("- [ ]", "- [x]", 1)
        return f"{updated} ✅{done_str}\n"

    patch_line(vault_root, relative, line, transform)

    return {
        "path": relative,
        "line": line,
        "task_text": task_text,
        "done_date": done_str,
        "patched": True,
    }


def set_task_date_in_file(
    vault_root: str,
    relative: str,
    line: int,
    date_type: str,
    new_date: str | None,
) -> dict[str, Any]:
    emoji = DATE_EMOJI[date_type]
    pattern = DATE_PATTERN[date_type]

    abs_path = resolve(vault_root, relative)
    content = abs_path.read_text(encoding="utf-8", errors="replace")
    raw_lines = content.splitlines(keepends=True)

    if line < 1 or line > len(raw_lines):
        raise TaskStateError(f"Line {line} out of range (file has {len(raw_lines)} lines)")

    original = raw_lines[line - 1].rstrip("\n")
    existing_match = pattern.search(original)
    date_before = existing_match.group(1) if existing_match else None

    def transform(raw_line: str) -> str:
        stripped = raw_line.rstrip("\n")
        current = pattern.search(stripped)
        if current and new_date is not None:
            result = pattern.sub(f"{emoji}{new_date}", stripped)
        elif current and new_date is None:
            result = pattern.sub("", stripped).rstrip()
            result = re.sub(r"  +", " ", result)
        elif not current and new_date is not None:
            result = f"{stripped.rstrip()} {emoji}{new_date}"
        else:
            result = stripped
        return result + "\n"

    patch_line(vault_root, relative, line, transform)

    return {
        "path": relative,
        "line": line,
        "date_type": date_type,
        "date_before": date_before,
        "date_after": new_date,
        "patched": True,
    }


def add_task_to_file(
    vault_root: str,
    relative: str,
    text: str,
    tags: list[str],
    scheduled_date: str | None,
    due_date: str | None,
    start_date: str | None,
    priority: str,
    stamp_created: bool,
    append_under_heading: str | None,
) -> dict[str, Any]:
    abs_path = resolve(vault_root, relative)
    task_line = _build_task_line(text, tags, scheduled_date, due_date, start_date, priority, stamp_created)

    if not abs_path.exists():
        atomic_write(abs_path, (task_line + "\n").encode("utf-8"))
        return {"path": relative, "task_line": task_line, "line": 1, "created": True}

    content = abs_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    insert_idx = _find_insert_position(lines, append_under_heading)
    lines.insert(insert_idx, task_line + "\n")
    atomic_write(abs_path, "".join(lines).encode("utf-8"))

    return {
        "path": relative,
        "task_line": task_line,
        "line": insert_idx + 1,
        "created": False,
    }


def _build_task_line(
    text: str,
    tags: list[str],
    scheduled_date: str | None,
    due_date: str | None,
    start_date: str | None,
    priority: str,
    stamp_created: bool,
) -> str:
    parts = [f"- [ ] {text}"]
    if tags:
        parts.append(" ".join(tags))
    if priority:
        parts.append(PRIORITY_EMOJI[priority])
    if stamp_created:
        parts.append(f"➕{date.today().isoformat()}")
    if scheduled_date:
        parts.append(f"⏳{scheduled_date}")
    if due_date:
        parts.append(f"📅{due_date}")
    if start_date:
        parts.append(f"🛫{start_date}")
    return " ".join(parts)


def _find_insert_position(lines: list[str], heading: str | None) -> int:
    if heading is None:
        return len(lines)

    heading_idx = None
    heading_level = 0

    for i, line in enumerate(lines):
        hm = re.match(r"^(#{1,6})\s+(.+)$", line.rstrip("\n"))
        if hm and hm.group(2).strip() == heading.strip():
            heading_idx = i
            heading_level = len(hm.group(1))
            break

    if heading_idx is None:
        return len(lines)

    last_task_idx = heading_idx
    for i in range(heading_idx + 1, len(lines)):
        hm = re.match(r"^(#{1,6})\s+", lines[i].rstrip("\n"))
        if hm and len(hm.group(1)) <= heading_level:
            break
        if re.match(r"^\s*- \[[ x/>\-]\]", lines[i]):
            last_task_idx = i

    return last_task_idx + 1

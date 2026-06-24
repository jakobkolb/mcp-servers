from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from mcp_obsidian.vault.frontmatter import extract_tags
from mcp_obsidian.vault.patterns import INLINE_TAG_RE

GLOBAL_EXCLUDE: dict[str, Any] = {
    "folders": ["Utility"],
    "tags": ["#exclude-master-tasklist", "#completed"],
    "headings": [
        "Morgens - 2 Minuten Check In",
        "Abends - 10 Minuten Cleanup",
    ],
}

TASK_LINE_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"- \[(?P<status>[x/ >\-])\] "
    r"(?P<text>.+)$"
)

DATE_RE: dict[str, re.Pattern[str]] = {
    "due": re.compile(r"📅\s?(\d{4}-\d{2}-\d{2})"),
    "scheduled": re.compile(r"⏳\s?(\d{4}-\d{2}-\d{2})"),
    "start": re.compile(r"🛫\s?(\d{4}-\d{2}-\d{2})"),
    "created": re.compile(r"➕\s?(\d{4}-\d{2}-\d{2})"),
    "done": re.compile(r"✅\s?(\d{4}-\d{2}-\d{2})"),
}

RECURRENCE_RE = re.compile(r"🔁\s?([^📅⏳🛫➕✅🔁\n]+)")

PRIORITY_MAP = [
    ("🔺", "highest"),
    ("⏫", "high"),
    ("🔼", "medium"),
    ("🔽", "low"),
    ("⏬", "lowest"),
]


@dataclass
class RawTask:
    path: str
    line: int
    raw_line: str
    status: str
    text: str
    tags: list[str]
    priority: str
    due_date: str | None
    scheduled_date: str | None
    start_date: str | None
    created_date: str | None
    done_date: str | None
    recurrence: str
    section: str = ""
    page_tags: list[str] = field(default_factory=list)
    page_ctime: float = 0.0
    page_created: str | None = None


def parse_task_line(line: str, path: str, lineno: int) -> RawTask | None:
    m = TASK_LINE_RE.match(line)
    if not m:
        return None

    raw_text = m.group("text")
    status = m.group("status")

    dates: dict[str, str | None] = {}
    for field_name, pattern in DATE_RE.items():
        dm = pattern.search(raw_text)
        dates[field_name] = dm.group(1) if dm else None

    rm = RECURRENCE_RE.search(raw_text)
    recurrence = rm.group(1).strip() if rm else ""

    priority = ""
    for emoji, level in PRIORITY_MAP:
        if emoji in raw_text:
            priority = level
            break

    tags = [f"#{t}" for t in INLINE_TAG_RE.findall(raw_text)]

    clean_text = raw_text
    for pattern in DATE_RE.values():
        clean_text = pattern.sub("", clean_text)
    clean_text = RECURRENCE_RE.sub("", clean_text)
    for emoji, _ in PRIORITY_MAP:
        clean_text = clean_text.replace(emoji, "")
    clean_text = clean_text.strip()

    return RawTask(
        path=path,
        line=lineno,
        raw_line=line,
        status=status,
        text=clean_text,
        tags=tags,
        priority=priority,
        due_date=dates["due"],
        scheduled_date=dates["scheduled"],
        start_date=dates["start"],
        created_date=dates["created"],
        done_date=dates["done"],
        recurrence=recurrence,
    )


def collect_tasks_from_file(
    vault_root: str,
    rel_path: str,
    page_fm: dict[str, Any],
    page_ctime: float,
) -> list[RawTask]:
    abs_path = Path(vault_root) / rel_path
    content = abs_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    page_tags = extract_tags(page_fm)
    page_created = str(page_fm.get("created", "")) or None

    current_section = ""
    in_code_block = False
    tasks: list[RawTask] = []

    for i, line in enumerate(lines, start=1):
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        heading_match = re.match(r"^#{1,6}\s+(.+)$", line)
        if heading_match:
            current_section = heading_match.group(1).strip()
            continue

        task = parse_task_line(line, rel_path, i)
        if task and task.status == " ":
            task.section = current_section
            task.page_tags = page_tags
            task.page_ctime = page_ctime
            task.page_created = page_created
            tasks.append(task)

    return tasks


def is_future_scheduled(task: RawTask) -> bool:
    if not task.scheduled_date:
        return False
    try:
        return date.fromisoformat(task.scheduled_date) > date.today()
    except ValueError:
        return False

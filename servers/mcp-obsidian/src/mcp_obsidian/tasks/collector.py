from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_obsidian.tasks.parser import (
    GLOBAL_EXCLUDE,
    RawTask,
    collect_tasks_from_file,
    extract_tags,
    is_future_scheduled,
)
from mcp_obsidian.vault.frontmatter import parse as parse_fm

GROUP_ORDER = {"waiting": 0, "priority": 1, "normal": 2, "notag": 3, "someday": 4}


def is_project_note(fm: dict[str, Any]) -> bool:
    tags = extract_tags(fm)
    has_project_tag = any(t.lower() in ("#project", "project") for t in tags)
    return (
        has_project_tag
        and not fm.get("completed", False)
        and not fm.get("inactive", False)
    )


def should_exclude_file(path: str, fm: dict[str, Any]) -> bool:
    for folder in GLOBAL_EXCLUDE["folders"]:
        if path.startswith(folder + "/") or path.startswith(folder + "\\"):
            return True
    page_tags = extract_tags(fm)
    for tag in GLOBAL_EXCLUDE["tags"]:
        if tag in page_tags or tag.lstrip("#") in page_tags:
            return True
    return False


def apply_project_sequencing(tasks: list[RawTask]) -> list[RawTask]:
    """Surface only the first task per section (GTD sequencing). Parallel sections (🟰) bypass this."""
    seen_sections: set[str] = set()
    result: list[RawTask] = []

    for task in tasks:
        section = task.section if task.section else "root"

        if "exclude" in section.lower():
            continue

        if "🟰" in section:
            result.append(task)
            continue

        if section not in seen_sections:
            seen_sections.add(section)
            result.append(task)

    return result


def process_project_note(
    vault_root: str,
    rel_path: str,
    page_fm: dict[str, Any],
    page_ctime: float,
) -> tuple[list[RawTask], bool]:
    all_tasks = collect_tasks_from_file(vault_root, rel_path, page_fm, page_ctime)
    open_tasks = [t for t in all_tasks if t.status == " "]
    if not open_tasks:
        return [], False
    return apply_project_sequencing(open_tasks), True


def process_non_project_note(
    vault_root: str,
    rel_path: str,
    page_fm: dict[str, Any],
    page_ctime: float,
    excluded_headings: list[str],
) -> list[RawTask]:
    all_tasks = collect_tasks_from_file(vault_root, rel_path, page_fm, page_ctime)
    return [
        t
        for t in all_tasks
        if t.status == " "
        and "#exclude" not in t.tags
        and t.section not in excluded_headings
        and "exclude" not in t.section.lower()
    ]


def assign_group(task: RawTask, page_tags: list[str]) -> str:
    if "#someday" in task.tags:
        return "someday"
    if "#waiting-on" in task.tags:
        return "waiting"
    if "🔼" in task.raw_line or "#🔼" in page_tags:
        return "priority"
    if len(task.tags) == 0:
        return "notag"
    return "normal"


def resolve_sort_date(task: RawTask, page_fm: dict[str, Any], page_ctime: float) -> int:
    if task.created_date:
        try:
            return int(datetime.fromisoformat(task.created_date).timestamp() * 1000)
        except ValueError:
            pass
    if "created" in page_fm:
        val = page_fm["created"]
        if hasattr(val, "timestamp"):
            return int(val.timestamp() * 1000)
        try:
            return int(datetime.fromisoformat(str(val)).timestamp() * 1000)
        except ValueError:
            pass
    return int(page_ctime * 1000)


def collect_all_tasks(
    vault_root: str,
    context_tag: str | None = None,
    group_filter: str | None = None,
    hide_future_scheduled: bool = True,
    include_someday: bool = False,
    include_waiting: bool = True,
    project_tasks_only: bool = False,
    exclude_projects: bool = False,
) -> dict[str, Any]:
    vault = Path(vault_root)
    tasks: list[dict[str, Any]] = []
    projects_without_na: list[dict[str, str]] = []

    for md_file in vault.rglob("*.md"):
        rel_path = str(md_file.relative_to(vault))
        try:
            raw = md_file.read_text(encoding="utf-8", errors="replace")
            fm, _ = parse_fm(raw)
        except OSError:
            continue

        page_ctime = md_file.stat().st_ctime

        if should_exclude_file(rel_path, fm):
            continue

        _is_project = is_project_note(fm)

        if project_tasks_only and not _is_project:
            continue
        if exclude_projects and _is_project:
            continue

        if _is_project:
            raw_tasks, has_na = process_project_note(vault_root, rel_path, fm, page_ctime)
            if not has_na:
                projects_without_na.append({"name": md_file.stem, "path": rel_path})
        else:
            raw_tasks = process_non_project_note(
                vault_root, rel_path, fm, page_ctime, GLOBAL_EXCLUDE["headings"]
            )

        for raw_task in raw_tasks:
            if hide_future_scheduled and is_future_scheduled(raw_task):
                continue

            group = assign_group(raw_task, raw_task.page_tags)

            if group_filter and group != group_filter:
                continue
            if not include_someday and group == "someday":
                continue
            if not include_waiting and group == "waiting":
                continue
            if context_tag and context_tag not in raw_task.tags:
                continue

            sort_date = resolve_sort_date(raw_task, fm, page_ctime)

            tasks.append(
                {
                    "path": rel_path,
                    "line": raw_task.line,
                    "raw_line": raw_task.raw_line,
                    "text": raw_task.text,
                    "tags": raw_task.tags,
                    "due_date": raw_task.due_date,
                    "scheduled_date": raw_task.scheduled_date,
                    "start_date": raw_task.start_date,
                    "created_date": raw_task.created_date,
                    "priority": raw_task.priority,
                    "recurrence": raw_task.recurrence,
                    "group": group,
                    "sort_date_ms": sort_date,
                    "project_name": md_file.stem if _is_project else None,
                    "project_path": rel_path if _is_project else None,
                    "project_section": raw_task.section or None,
                    "is_sequenced": _is_project,
                }
            )

    tasks.sort(key=lambda t: (GROUP_ORDER.get(t["group"], 99), t["sort_date_ms"]))

    return {
        "tasks": tasks,
        "projects_without_next_action": projects_without_na,
        "total_tasks": len(tasks),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

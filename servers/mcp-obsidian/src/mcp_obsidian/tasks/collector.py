from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from mcp_obsidian.tasks.parser import (
    GLOBAL_EXCLUDE,
    PRIORITY_MARKER,
    RawTask,
    collect_tasks_from_file,
    is_available,
)
from mcp_obsidian.vault.frontmatter import extract_tags
from mcp_obsidian.vault.frontmatter import parse as parse_fm


def is_project_note(fm: dict[str, Any]) -> bool:
    tags = extract_tags(fm)
    has_project_tag = any(t.lower() in ("#project", "project") for t in tags)
    return has_project_tag and not fm.get("completed", False) and not fm.get("inactive", False)


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
    """Surface only the first task per section (GTD sequencing). Parallel sections (🟰) bypass."""
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
    apply_sequencing: bool = True,
) -> tuple[list[RawTask], bool]:
    """Return the project's candidate tasks and whether it has a next action at all.

    Availability is deliberately NOT applied here. Sequencing must pick the first
    open task of each section first; filtering beforehand would step over a
    deferred next action and promote the task behind it, which under strict
    sequencing is work that cannot be done yet.
    """
    all_tasks = collect_tasks_from_file(vault_root, rel_path, page_fm, page_ctime)
    open_tasks = [t for t in all_tasks if t.status == " "]
    if not open_tasks:
        return [], False
    if apply_sequencing:
        return apply_project_sequencing(open_tasks), True
    return open_tasks, True


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


def resolve_priority(task: RawTask) -> bool:
    """Whether the task is priority, from its own marker or inherited.

    A task in a project note whose frontmatter carries the marker is a priority
    task even without one of its own. Priority is a facet orthogonal to the
    task's tags, not a bucket competing with them: a task can be priority and
    #waiting-on and #context/phone at once, and a query for any of the three
    must return it.
    """
    return task.priority or f"#{PRIORITY_MARKER}" in task.page_tags


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
    tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    priority: bool | None = None,
    untagged: bool | None = None,
    available_on: date | None = None,
    project_tasks_only: bool = False,
    exclude_projects: bool = False,
    apply_sequencing: bool = True,
    path: str | None = None,
) -> dict[str, Any]:
    vault = Path(vault_root)
    tasks: list[dict[str, Any]] = []
    projects_without_na: list[dict[str, str]] = []

    for md_file in vault.rglob("*.md"):
        rel_path = str(md_file.relative_to(vault))
        if path and not rel_path.startswith(path):
            continue
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
            raw_tasks, has_na = process_project_note(
                vault_root,
                rel_path,
                fm,
                page_ctime,
                apply_sequencing=apply_sequencing,
            )
            if not has_na:
                projects_without_na.append({"name": md_file.stem, "path": rel_path})
        else:
            raw_tasks = process_non_project_note(
                vault_root, rel_path, fm, page_ctime, GLOBAL_EXCLUDE["headings"]
            )

        for raw_task in raw_tasks:
            # Applied after sequencing has chosen the next action, so an
            # unavailable next action silences its section rather than promoting
            # the task behind it.
            if available_on is not None and not is_available(raw_task, available_on):
                continue

            task_priority = resolve_priority(raw_task)

            # Facets are independent membership tests that AND together; a task
            # belongs to every one that applies to it, not to a single bucket.
            if priority is not None and task_priority != priority:
                continue
            if tags and not all(t in raw_task.tags for t in tags):
                continue
            if exclude_tags and any(t in raw_task.tags for t in exclude_tags):
                continue
            if untagged is not None and (len(raw_task.tags) == 0) != untagged:
                continue

            sort_date = resolve_sort_date(raw_task, fm, page_ctime)

            tasks.append(
                {
                    "path": rel_path,
                    "line": raw_task.line,
                    "raw_line": raw_task.raw_line,
                    "text": raw_task.text,
                    "tags": raw_task.tags,
                    "scheduled_date": raw_task.scheduled_date,
                    "created_date": raw_task.created_date,
                    "priority": task_priority,
                    "recurrence": raw_task.recurrence,
                    "sort_date_ms": sort_date,
                    "project_name": md_file.stem if _is_project else None,
                    "project_path": rel_path if _is_project else None,
                    "project_section": raw_task.section or None,
                    "project_task": _is_project,
                }
            )

    # Priority first, then oldest first within each.
    tasks.sort(key=lambda t: (not t["priority"], t["sort_date_ms"]))

    return {
        "tasks": tasks,
        "projects_without_next_action": projects_without_na,
        "total_tasks": len(tasks),
        "generated_at": datetime.now(UTC).isoformat(),
    }

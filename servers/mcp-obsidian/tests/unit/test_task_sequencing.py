from __future__ import annotations

from mcp_obsidian.tasks.collector import apply_project_sequencing, is_project_note
from mcp_obsidian.tasks.parser import RawTask


def make_task(section: str, scheduled_date: str | None = None, line: int = 1) -> RawTask:
    return RawTask(
        path="Projects/test.md",
        line=line,
        raw_line=f"- [ ] Task {line}",
        status=" ",
        text=f"Task {line}",
        tags=[],
        priority="",
        due_date=None,
        scheduled_date=scheduled_date,
        start_date=None,
        created_date=None,
        done_date=None,
        recurrence="",
        section=section,
    )


# ---------------------------------------------------------------------------
# is_project_note
# ---------------------------------------------------------------------------


def test_is_project_note_with_project_tag():
    assert is_project_note({"tags": ["project"]}) is True


def test_is_project_note_with_hash_project_tag():
    assert is_project_note({"tags": ["#project"]}) is True


def test_is_project_note_without_project_tag():
    assert is_project_note({"tags": ["someday"]}) is False


def test_is_project_note_completed():
    assert is_project_note({"tags": ["project"], "completed": True}) is False


def test_is_project_note_inactive():
    assert is_project_note({"tags": ["project"], "inactive": True}) is False


def test_is_project_note_no_tags():
    assert is_project_note({}) is False


# ---------------------------------------------------------------------------
# apply_project_sequencing — sequential sections
# ---------------------------------------------------------------------------


def test_sequential_section_surfaces_only_first_task():
    tasks = [make_task("Planning", line=1), make_task("Planning", line=2)]
    result = apply_project_sequencing(tasks)
    assert len(result) == 1
    assert result[0].line == 1


def test_multiple_sequential_sections_first_each():
    tasks = [
        make_task("Planning", line=1),
        make_task("Planning", line=2),
        make_task("Execution", line=3),
        make_task("Execution", line=4),
    ]
    result = apply_project_sequencing(tasks)
    assert len(result) == 2
    assert {t.line for t in result} == {1, 3}


def test_single_task_section_is_surfaced():
    tasks = [make_task("Planning", line=1)]
    result = apply_project_sequencing(tasks)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# apply_project_sequencing — parallel sections (🟰)
# ---------------------------------------------------------------------------


def test_parallel_section_surfaces_all_tasks():
    tasks = [make_task("Execution 🟰", line=1), make_task("Execution 🟰", line=2)]
    result = apply_project_sequencing(tasks)
    assert len(result) == 2


def test_parallel_section_mixed_with_sequential():
    tasks = [
        make_task("Planning", line=1),
        make_task("Planning", line=2),
        make_task("Parallel 🟰", line=3),
        make_task("Parallel 🟰", line=4),
    ]
    result = apply_project_sequencing(tasks)
    # 1 from Planning + 2 from Parallel
    assert len(result) == 3
    assert result[0].line == 1
    assert {t.line for t in result[1:]} == {3, 4}


# ---------------------------------------------------------------------------
# apply_project_sequencing — excluded sections
# ---------------------------------------------------------------------------


def test_excluded_section_is_skipped():
    tasks = [make_task("Done #exclude", line=1)]
    result = apply_project_sequencing(tasks)
    assert result == []


def test_exclude_keyword_case_insensitive():
    tasks = [make_task("EXCLUDE me", line=1), make_task("Exclude This", line=2)]
    result = apply_project_sequencing(tasks)
    assert result == []


def test_excluded_section_does_not_block_other_sections():
    tasks = [
        make_task("Done #exclude", line=1),
        make_task("Planning", line=2),
    ]
    result = apply_project_sequencing(tasks)
    assert len(result) == 1
    assert result[0].line == 2


# ---------------------------------------------------------------------------
# apply_project_sequencing — empty input
# ---------------------------------------------------------------------------


def test_empty_task_list_returns_empty():
    assert apply_project_sequencing([]) == []


# ---------------------------------------------------------------------------
# apply_project_sequencing — root section (no heading)
# ---------------------------------------------------------------------------


def test_root_section_treated_as_single_sequential_bucket():
    tasks = [make_task("", line=1), make_task("", line=2)]
    result = apply_project_sequencing(tasks)
    assert len(result) == 1
    assert result[0].line == 1

from __future__ import annotations

from pathlib import Path

from mcp_obsidian.tasks.parser import (
    collect_tasks_from_file,
    extract_tags,
    is_future_scheduled,
    parse_task_line,
)

# ---------------------------------------------------------------------------
# parse_task_line
# ---------------------------------------------------------------------------


def test_parse_simple_open_task():
    task = parse_task_line("- [ ] Buy milk", "note.md", 1)
    assert task is not None
    assert task.status == " "
    assert task.text == "Buy milk"
    assert task.tags == []
    assert task.priority == ""


def test_parse_completed_task_returns_none_status():
    task = parse_task_line("- [x] Done thing", "note.md", 1)
    assert task is not None
    assert task.status == "x"


def test_parse_returns_none_for_non_task_line():
    assert parse_task_line("Just a paragraph", "note.md", 1) is None
    assert parse_task_line("# Heading", "note.md", 2) is None
    assert parse_task_line("", "note.md", 3) is None


def test_parse_extracts_tags():
    task = parse_task_line("- [ ] Call doctor #context/phone #waiting-on", "note.md", 1)
    assert task is not None
    assert "#context/phone" in task.tags
    assert "#waiting-on" in task.tags


def test_parse_extracts_due_date():
    task = parse_task_line("- [ ] Submit report 📅2026-06-30", "note.md", 1)
    assert task is not None
    assert task.due_date == "2026-06-30"


def test_parse_extracts_scheduled_date():
    task = parse_task_line("- [ ] Review PR ⏳2026-05-20", "note.md", 1)
    assert task is not None
    assert task.scheduled_date == "2026-05-20"


def test_parse_extracts_created_date():
    task = parse_task_line("- [ ] Do laundry ➕2026-05-01", "note.md", 1)
    assert task is not None
    assert task.created_date == "2026-05-01"


def test_parse_extracts_priority_highest():
    task = parse_task_line("- [ ] Urgent task 🔺", "note.md", 1)
    assert task is not None
    assert task.priority == "highest"


def test_parse_extracts_priority_medium():
    task = parse_task_line("- [ ] Medium task 🔼", "note.md", 1)
    assert task is not None
    assert task.priority == "medium"


def test_parse_strips_emoji_metadata_from_text():
    task = parse_task_line(
        "- [ ] Buy groceries #context/home ➕2026-05-01 ⏳2026-05-10 📅2026-05-15",
        "note.md",
        1,
    )
    assert task is not None
    assert "➕" not in task.text
    assert "⏳" not in task.text
    assert "📅" not in task.text
    assert "Buy groceries" in task.text


def test_parse_strips_priority_emoji_from_text():
    task = parse_task_line("- [ ] Urgent task 🔺 do this now", "note.md", 1)
    assert task is not None
    assert "🔺" not in task.text


def test_parse_sets_path_and_line():
    task = parse_task_line("- [ ] Do thing", "Projects/MyProject.md", 42)
    assert task is not None
    assert task.path == "Projects/MyProject.md"
    assert task.line == 42


def test_parse_task_with_german_umlauts_in_tag():
    task = parse_task_line("- [ ] Aufgabe #kontext/büro", "note.md", 1)
    assert task is not None
    assert "#kontext/büro" in task.tags


# ---------------------------------------------------------------------------
# collect_tasks_from_file
# ---------------------------------------------------------------------------


def test_collect_finds_open_tasks(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(
        "# Todo\n- [ ] First task #context/pc\n- [x] Done task\n- [ ] Second task\n",
        encoding="utf-8",
    )
    tasks = collect_tasks_from_file(str(tmp_path), "note.md", {}, 0.0)
    assert len(tasks) == 2  # only open tasks
    assert "First task" in tasks[0].text
    assert "Second task" in tasks[1].text


def test_collect_sets_section_from_heading(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(
        "## My Section\n- [ ] Task under heading\n",
        encoding="utf-8",
    )
    tasks = collect_tasks_from_file(str(tmp_path), "note.md", {}, 0.0)
    assert tasks[0].section == "My Section"


def test_collect_skips_tasks_in_code_blocks(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(
        "```\n- [ ] Not a real task\n```\n- [ ] Real task\n",
        encoding="utf-8",
    )
    tasks = collect_tasks_from_file(str(tmp_path), "note.md", {}, 0.0)
    assert len(tasks) == 1
    assert tasks[0].text == "Real task"


def test_collect_sets_page_tags_from_frontmatter(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Task\n", encoding="utf-8")
    fm = {"tags": ["project"]}
    tasks = collect_tasks_from_file(str(tmp_path), "note.md", fm, 0.0)
    assert "#project" in tasks[0].page_tags


# ---------------------------------------------------------------------------
# extract_tags
# ---------------------------------------------------------------------------


def test_extract_tags_normalizes_to_hash_prefix():
    assert extract_tags({"tags": ["project", "gtd"]}) == ["#project", "#gtd"]


def test_extract_tags_handles_string_value():
    assert extract_tags({"tags": "project"}) == ["#project"]


def test_extract_tags_strips_existing_hash():
    assert extract_tags({"tags": ["#project"]}) == ["#project"]


def test_extract_tags_empty():
    assert extract_tags({}) == []


# ---------------------------------------------------------------------------
# is_future_scheduled
# ---------------------------------------------------------------------------


def test_is_future_scheduled_true_for_future_date():
    task = parse_task_line("- [ ] Thing ⏳2099-01-01", "note.md", 1)
    assert task is not None
    assert is_future_scheduled(task) is True


def test_is_future_scheduled_false_for_past_date():
    task = parse_task_line("- [ ] Thing ⏳2020-01-01", "note.md", 1)
    assert task is not None
    assert is_future_scheduled(task) is False


def test_is_future_scheduled_false_when_no_date():
    task = parse_task_line("- [ ] No date", "note.md", 1)
    assert task is not None
    assert is_future_scheduled(task) is False

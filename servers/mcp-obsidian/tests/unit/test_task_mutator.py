from __future__ import annotations

from pathlib import Path

import pytest
from mcp_obsidian.errors import TaskStateError
from mcp_obsidian.tasks.mutator import (
    _build_task_line,
    _find_insert_position,
    add_task_to_file,
    complete_task_in_file,
    set_task_date_in_file,
)

# ---------------------------------------------------------------------------
# _build_task_line
# ---------------------------------------------------------------------------


def test_build_task_line_minimal():
    line = _build_task_line("Buy milk", [], None, None, None, "", False)
    assert line == "- [ ] Buy milk"


def test_build_task_line_with_tags():
    line = _build_task_line("Call doctor", ["#context/phone"], None, None, None, "", False)
    assert "#context/phone" in line


def test_build_task_line_with_priority():
    line = _build_task_line("Urgent", [], None, None, None, "highest", False)
    assert "🔺" in line


def test_build_task_line_with_stamp_created():
    line = _build_task_line("Task", [], None, None, None, "", True)
    assert "➕" in line


def test_build_task_line_with_scheduled():
    line = _build_task_line("Review PR", [], "2026-06-01", None, None, "", False)
    assert "⏳2026-06-01" in line


def test_build_task_line_with_due():
    line = _build_task_line("Submit", [], None, "2026-06-15", None, "", False)
    assert "📅2026-06-15" in line


def test_build_task_line_full():
    line = _build_task_line(
        "Complex task", ["#context/pc"], "2026-06-01", "2026-06-15", None, "high", True
    )
    assert line.startswith("- [ ] Complex task")
    assert "#context/pc" in line
    assert "⏫" in line
    assert "➕" in line
    assert "⏳2026-06-01" in line
    assert "📅2026-06-15" in line


# ---------------------------------------------------------------------------
# complete_task_in_file
# ---------------------------------------------------------------------------


def test_complete_task_marks_done(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Buy milk\n", encoding="utf-8")

    result = complete_task_in_file(str(tmp_path), "note.md", 1, "2026-05-13")

    assert result["patched"] is True
    assert result["done_date"] == "2026-05-13"
    content = note.read_text(encoding="utf-8")
    assert "- [x] Buy milk" in content
    assert "✅2026-05-13" in content


def test_complete_task_uses_today_when_no_date(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Buy milk\n", encoding="utf-8")

    result = complete_task_in_file(str(tmp_path), "note.md", 1)

    from datetime import date

    assert result["done_date"] == date.today().isoformat()


def test_complete_task_raises_for_already_done(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [x] Already done\n", encoding="utf-8")

    with pytest.raises(TaskStateError, match="open task marker"):
        complete_task_in_file(str(tmp_path), "note.md", 1)


def test_complete_task_raises_for_out_of_range(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Task\n", encoding="utf-8")

    with pytest.raises(TaskStateError, match="out of range"):
        complete_task_in_file(str(tmp_path), "note.md", 99)


def test_complete_task_preserves_other_lines(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("Header\n- [ ] Task\nFooter\n", encoding="utf-8")

    complete_task_in_file(str(tmp_path), "note.md", 2, "2026-05-13")

    lines = note.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Header"
    assert lines[2] == "Footer"


def test_complete_task_with_emoji_content(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Buy milk 🥛 #context/home ➕2026-05-01\n", encoding="utf-8")

    result = complete_task_in_file(str(tmp_path), "note.md", 1, "2026-05-13")

    assert result["patched"] is True
    content = note.read_text(encoding="utf-8")
    assert "- [x]" in content
    assert "✅2026-05-13" in content


# ---------------------------------------------------------------------------
# set_task_date_in_file
# ---------------------------------------------------------------------------


def test_set_task_date_adds_new_scheduled(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Task\n", encoding="utf-8")

    result = set_task_date_in_file(str(tmp_path), "note.md", 1, "scheduled", "2026-06-01")

    assert result["date_before"] is None
    assert result["date_after"] == "2026-06-01"
    assert "⏳2026-06-01" in note.read_text(encoding="utf-8")


def test_set_task_date_replaces_existing(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Task ⏳2026-05-01\n", encoding="utf-8")

    result = set_task_date_in_file(str(tmp_path), "note.md", 1, "scheduled", "2026-06-01")

    assert result["date_before"] == "2026-05-01"
    assert result["date_after"] == "2026-06-01"
    assert "⏳2026-06-01" in note.read_text(encoding="utf-8")
    assert "⏳2026-05-01" not in note.read_text(encoding="utf-8")


def test_set_task_date_removes_when_none(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Task ⏳2026-05-01\n", encoding="utf-8")

    result = set_task_date_in_file(str(tmp_path), "note.md", 1, "scheduled", None)

    assert result["date_before"] == "2026-05-01"
    assert result["date_after"] is None
    assert "⏳" not in note.read_text(encoding="utf-8")


def test_set_task_date_raises_out_of_range(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Task\n", encoding="utf-8")

    with pytest.raises(TaskStateError):
        set_task_date_in_file(str(tmp_path), "note.md", 99, "due", "2026-06-01")


# ---------------------------------------------------------------------------
# add_task_to_file
# ---------------------------------------------------------------------------


def test_add_task_creates_file_when_missing(tmp_path: Path):
    result = add_task_to_file(
        str(tmp_path), "new.md", "Buy milk", [], None, None, None, "", False, None
    )

    assert result["created"] is True
    assert result["line"] == 1
    assert (tmp_path / "new.md").exists()


def test_add_task_appends_to_existing_file(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("# Notes\n\nExisting content\n", encoding="utf-8")

    result = add_task_to_file(
        str(tmp_path), "note.md", "New task", [], None, None, None, "", False, None
    )

    assert result["created"] is False
    content = note.read_text(encoding="utf-8")
    assert "- [ ] New task" in content


def test_add_task_inserts_under_heading(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("## Todo\n- [ ] Existing task\n## Done\n", encoding="utf-8")

    add_task_to_file(str(tmp_path), "note.md", "New task", [], None, None, None, "", False, "Todo")

    lines = note.read_text(encoding="utf-8").splitlines()
    todo_idx = lines.index("## Todo")
    done_idx = lines.index("## Done")
    task_positions = [i for i, ln in enumerate(lines) if "- [ ]" in ln or "- [x]" in ln]
    # Both tasks should be between ## Todo and ## Done
    for pos in task_positions:
        assert todo_idx < pos < done_idx


def test_add_task_appends_to_end_when_heading_missing(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("Some content\n", encoding="utf-8")

    add_task_to_file(
        str(tmp_path), "note.md", "Task", [], None, None, None, "", False, "Nonexistent Heading"
    )

    content = note.read_text(encoding="utf-8")
    assert content.endswith("- [ ] Task\n")


# ---------------------------------------------------------------------------
# _find_insert_position
# ---------------------------------------------------------------------------


def test_find_insert_position_none_heading_returns_end():
    lines = ["line1\n", "line2\n"]
    assert _find_insert_position(lines, None) == 2


def test_find_insert_position_after_last_task_under_heading():
    lines = [
        "## Todo\n",
        "- [ ] First\n",
        "- [ ] Second\n",
        "## Done\n",
    ]
    pos = _find_insert_position(lines, "Todo")
    assert pos == 3  # after "- [ ] Second"

from __future__ import annotations

from pathlib import Path

import pytest
from mcp_obsidian.errors import PatchAmbiguousError, PatchNoMatchError, TaskStateError
from mcp_obsidian.vault.io import atomic_write, patch_line, patch_note

# ---------------------------------------------------------------------------
# atomic_write
# ---------------------------------------------------------------------------


def test_atomic_write_creates_file(tmp_path: Path):
    target = tmp_path / "note.md"
    atomic_write(target, b"hello")
    assert target.read_bytes() == b"hello"


def test_atomic_write_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "sub" / "dir" / "note.md"
    atomic_write(target, b"content")
    assert target.exists()


def test_atomic_write_overwrites_existing(tmp_path: Path):
    target = tmp_path / "note.md"
    target.write_bytes(b"old")
    atomic_write(target, b"new")
    assert target.read_bytes() == b"new"


def test_atomic_write_handles_emoji_content(tmp_path: Path):
    target = tmp_path / "note.md"
    content = "- [ ] Buy milk 🥛 ⏳2026-06-01\n".encode()
    atomic_write(target, content)
    assert target.read_bytes() == content


# ---------------------------------------------------------------------------
# patch_note
# ---------------------------------------------------------------------------


def test_patch_note_replaces_first_occurrence(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("hello world\ngoodbye again\n", encoding="utf-8")

    result = patch_note(str(tmp_path), "note.md", "hello", "goodbye")

    assert result["replacements"] == 1
    assert note.read_text(encoding="utf-8") == "goodbye world\ngoodbye again\n"


def test_patch_note_replace_all(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("foo foo foo\n", encoding="utf-8")

    result = patch_note(str(tmp_path), "note.md", "foo", "bar", replace_all=True)

    assert result["replacements"] == 3
    assert note.read_text(encoding="utf-8") == "bar bar bar\n"


def test_patch_note_raises_no_match(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("hello world\n", encoding="utf-8")

    with pytest.raises(PatchNoMatchError):
        patch_note(str(tmp_path), "note.md", "not_there", "x")


def test_patch_note_raises_ambiguous(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("foo foo\n", encoding="utf-8")

    with pytest.raises(PatchAmbiguousError):
        patch_note(str(tmp_path), "note.md", "foo", "bar")


def test_patch_note_handles_emoji(tmp_path: Path):
    content = "- [ ] Buy milk 🥛 ⏳2026-06-01\n"
    note = tmp_path / "note.md"
    note.write_text(content, encoding="utf-8")

    result = patch_note(str(tmp_path), "note.md", "⏳2026-06-01", "⏳2026-07-01")

    assert result["replacements"] == 1
    assert "⏳2026-07-01" in note.read_text(encoding="utf-8")


def test_patch_note_length_fields(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("abc\n", encoding="utf-8")

    result = patch_note(str(tmp_path), "note.md", "abc", "xy")

    assert result["old_string_length"] == 3
    assert result["new_string_length"] == 2


# ---------------------------------------------------------------------------
# patch_line
# ---------------------------------------------------------------------------


def test_patch_line_transforms_target_line(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("line one\nline two\nline three\n", encoding="utf-8")

    result = patch_line(str(tmp_path), "note.md", 2, lambda ln: ln.replace("two", "TWO"))

    assert result == "line TWO"
    lines = note.read_text(encoding="utf-8").splitlines()
    assert lines[1] == "line TWO"
    assert lines[0] == "line one"
    assert lines[2] == "line three"


def test_patch_line_raises_out_of_range(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("only one line\n", encoding="utf-8")

    with pytest.raises(TaskStateError):
        patch_line(str(tmp_path), "note.md", 5, lambda ln: ln)


def test_patch_line_first_line(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text("- [ ] Task\nOther line\n", encoding="utf-8")

    patch_line(str(tmp_path), "note.md", 1, lambda ln: ln.replace("[ ]", "[x]"))

    assert note.read_text(encoding="utf-8").startswith("- [x] Task")

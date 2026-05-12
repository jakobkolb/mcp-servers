from pathlib import Path

import pytest
from mcp_obsidian.errors import VaultPathError
from mcp_obsidian.vault import resolve, to_relative


def test_resolve_returns_absolute_path(tmp_path):
    assert resolve(tmp_path, "Diary/note.md") == tmp_path / "Diary" / "note.md"


def test_resolve_throws_when_file_is_outside_vault(tmp_path):
    with pytest.raises(VaultPathError, match="escapes"):
        resolve(str(tmp_path), "../note.md")


def test_emoji_in_path_works(tmp_path):
    assert resolve(tmp_path, "Diary/🎶 note.md") == tmp_path / "Diary" / "🎶 note.md"


def test_nested_paths_work(tmp_path):
    result = resolve(str(tmp_path), "Diary/2026/note.md")

    assert result == tmp_path / "Diary" / "2026" / "note.md"


def test_absolute_path_errors(tmp_path):
    with pytest.raises(VaultPathError, match="absolute"):
        resolve(str(tmp_path), "/Diary/2026/note.md")


def test_empty_relative_path_errors(tmp_path):
    with pytest.raises(VaultPathError, match="empty"):
        resolve(str(tmp_path), "")


def test_whitespace_relative_path_errors(tmp_path):
    with pytest.raises(VaultPathError, match="empty"):
        resolve(str(tmp_path), "   ")


def test_to_relative_round_trips(tmp_path: Path):
    relative = "Diary/2026/note.md"
    absolute = resolve(str(tmp_path), relative)

    assert to_relative(str(tmp_path), absolute) == relative

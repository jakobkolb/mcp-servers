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


@pytest.mark.parametrize(
    "relative",
    [
        ".obsidian/plugins/x/main.js",
        ".obsidian",
        "Diary/.hidden/note.md",
        ".trash/old.md",
        ".git/config",
        "Diary/../.obsidian/app.json",
    ],
)
def test_hidden_paths_are_rejected(tmp_path, relative):
    with pytest.raises(VaultPathError, match="Hidden"):
        resolve(str(tmp_path), relative)


def test_dotdot_that_stays_visible_is_still_allowed(tmp_path):
    assert resolve(str(tmp_path), "Diary/../note.md") == tmp_path / "note.md"


def test_names_that_merely_contain_a_dot_are_allowed(tmp_path):
    assert resolve(str(tmp_path), "Notes/v1.2 plan.md") == tmp_path / "Notes" / "v1.2 plan.md"


def test_symlink_into_a_hidden_directory_is_rejected(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / ".obsidian", target_is_directory=True)

    with pytest.raises(VaultPathError, match="Hidden"):
        resolve(str(tmp_path), "link/app.json")


def test_vault_root_inside_a_hidden_directory_is_fine(tmp_path):
    root = tmp_path / ".vault"
    root.mkdir()

    assert resolve(str(root), "note.md") == root / "note.md"

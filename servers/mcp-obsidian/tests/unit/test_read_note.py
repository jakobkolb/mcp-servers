from pathlib import Path

import pytest
from mcp_obsidian.errors import NotANoteError, NoteNotFoundError, VaultPathError
from mcp_obsidian.vault.io import read_note


def test_reads_note_with_frontmatter(tmp_vault: Path, note_with_frontmatter: Path):
    note = read_note(str(tmp_vault), "note_with_fm.md")

    assert note.path == "note_with_fm.md"
    assert note.frontmatter["title"] == "Test Note"
    assert note.frontmatter["completed"] is False
    assert "project" in note.frontmatter["tags"]
    assert "Body content here." in note.content
    assert note.raw.startswith("---")
    assert note.size == note_with_frontmatter.stat().st_size
    assert note.mtime.endswith("+00:00")


def test_reads_note_without_frontmatter(tmp_vault: Path, note_without_frontmatter: Path):
    note = read_note(str(tmp_vault), "plain_note.md")

    assert note.frontmatter == {}
    assert "Just a body." in note.content


def test_reads_note_in_subdirectory(tmp_vault: Path):
    subdir = tmp_vault / "Getting things done" / "Projects"
    subdir.mkdir(parents=True)
    (subdir / "My Project.md").write_text(
        "---\ntags:\n  - project\n---\n\n## Todo\n- [ ] First action\n",
        encoding="utf-8",
    )

    note = read_note(str(tmp_vault), "Getting things done/Projects/My Project.md")

    assert "project" in note.frontmatter["tags"]
    assert "First action" in note.content


def test_reads_note_with_emoji_in_name(tmp_vault: Path):
    (tmp_vault / "🚀 Next actions list.md").write_text(
        "---\ntitle: Next Actions\n---\n\n- [ ] First task\n",
        encoding="utf-8",
    )

    note = read_note(str(tmp_vault), "🚀 Next actions list.md")

    assert note.frontmatter["title"] == "Next Actions"
    assert "First task" in note.content


def test_raises_not_found_for_missing_file(tmp_vault: Path):
    with pytest.raises(NoteNotFoundError, match="does_not_exist.md"):
        read_note(str(tmp_vault), "does_not_exist.md")


def test_raises_not_a_note_for_txt_file(tmp_vault: Path):
    (tmp_vault / "file.txt").write_text("hello", encoding="utf-8")

    with pytest.raises(NotANoteError):
        read_note(str(tmp_vault), "file.txt")


def test_raises_not_a_note_for_directory(tmp_vault: Path):
    (tmp_vault / "subdir").mkdir()

    with pytest.raises(NotANoteError):
        read_note(str(tmp_vault), "subdir")


def test_raises_vault_path_error_for_traversal(tmp_vault: Path):
    with pytest.raises(VaultPathError):
        read_note(str(tmp_vault), "../outside.md")


def test_empty_note(tmp_vault: Path):
    (tmp_vault / "empty.md").write_text("", encoding="utf-8")

    note = read_note(str(tmp_vault), "empty.md")

    assert note.frontmatter == {}
    assert note.content == ""
    assert note.size == 0


# ---------------------------------------------------------------------------
# read_note handler – include_content / include_frontmatter flags
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _call_read_note(vault_path: Path, arguments: dict) -> dict:
    from unittest.mock import MagicMock

    from mcp_obsidian.config import Config
    from mcp_obsidian.tools.reading import get_handlers

    cfg = MagicMock(spec=Config)
    cfg.vault_path = str(vault_path)
    return await get_handlers(cfg)["read_note"](arguments)


@pytest.mark.asyncio
async def test_read_note_include_content_false_omits_body(tmp_path: Path):
    _write(tmp_path / "note.md", "---\ntitle: hi\n---\n\nBody text.\n")

    result = await _call_read_note(tmp_path, {"path": "note.md", "include_content": False})

    assert "content" not in result or result["content"] is None


@pytest.mark.asyncio
async def test_read_note_include_frontmatter_false_omits_frontmatter(tmp_path: Path):
    _write(tmp_path / "note.md", "---\ntitle: hi\n---\n\nBody text.\n")

    result = await _call_read_note(tmp_path, {"path": "note.md", "include_frontmatter": False})

    assert "frontmatter" not in result or result["frontmatter"] is None


@pytest.mark.asyncio
async def test_read_note_defaults_include_both(tmp_path: Path):
    _write(tmp_path / "note.md", "---\ntitle: hi\n---\n\nBody text.\n")

    result = await _call_read_note(tmp_path, {"path": "note.md"})

    assert result["content"] is not None
    assert result["frontmatter"] is not None

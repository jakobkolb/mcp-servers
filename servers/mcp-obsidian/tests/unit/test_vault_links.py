from __future__ import annotations

from pathlib import Path

from mcp_obsidian.vault.links import get_backlinks


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_get_backlinks_finds_simple_link(tmp_path: Path):
    _write(tmp_path / "target.md", "The target note.\n")
    _write(tmp_path / "source.md", "See [[target]] for details.\n")

    result = get_backlinks(str(tmp_path), "target.md")

    assert result["path"] == "target.md"
    assert len(result["backlinks"]) == 1
    assert result["backlinks"][0]["source_path"] == "source.md"


def test_get_backlinks_finds_aliased_link(tmp_path: Path):
    _write(tmp_path / "target.md", "Target.\n")
    _write(tmp_path / "source.md", "See [[target|My alias]] here.\n")

    result = get_backlinks(str(tmp_path), "target.md")

    assert len(result["backlinks"]) == 1


def test_get_backlinks_finds_heading_link(tmp_path: Path):
    _write(tmp_path / "target.md", "Target.\n")
    _write(tmp_path / "source.md", "See [[target#section]] here.\n")

    result = get_backlinks(str(tmp_path), "target.md")

    assert len(result["backlinks"]) == 1


def test_get_backlinks_excludes_self(tmp_path: Path):
    _write(tmp_path / "target.md", "Links to itself [[target]].\n")

    result = get_backlinks(str(tmp_path), "target.md")

    assert len(result["backlinks"]) == 0


def test_get_backlinks_returns_line_number(tmp_path: Path):
    _write(tmp_path / "target.md", "Target.\n")
    _write(tmp_path / "source.md", "First line.\nSecond [[target]] line.\n")

    result = get_backlinks(str(tmp_path), "target.md")

    assert result["backlinks"][0]["line"] == 2


def test_get_backlinks_returns_context_snippet(tmp_path: Path):
    _write(tmp_path / "target.md", "Target.\n")
    _write(tmp_path / "source.md", "See [[target]] for details.\n")

    result = get_backlinks(str(tmp_path), "target.md")

    assert "target" in result["backlinks"][0]["context"]


def test_get_backlinks_no_links(tmp_path: Path):
    _write(tmp_path / "target.md", "Target.\n")
    _write(tmp_path / "unrelated.md", "Nothing here.\n")

    result = get_backlinks(str(tmp_path), "target.md")

    assert result["backlinks"] == []
    assert result["total"] == 0


def test_get_backlinks_multiple_sources(tmp_path: Path):
    _write(tmp_path / "target.md", "Target.\n")
    _write(tmp_path / "a.md", "See [[target]].\n")
    _write(tmp_path / "b.md", "Also [[target]].\n")

    result = get_backlinks(str(tmp_path), "target.md")

    sources = {bl["source_path"] for bl in result["backlinks"]}
    assert "a.md" in sources
    assert "b.md" in sources

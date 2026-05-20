from __future__ import annotations

from pathlib import Path

from mcp_obsidian.vault.search import list_all_tags, search_notes


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# search_notes
# ---------------------------------------------------------------------------


def test_search_finds_match_in_body(tmp_path: Path):
    _write(tmp_path / "note.md", "---\ntitle: Test\n---\n\nFind me here.\n")

    result = search_notes(str(tmp_path), "Find me")

    assert result["total_found"] == 1
    assert result["results"][0]["path"] == "note.md"
    assert "Find me" in result["results"][0]["snippet"]


def test_search_returns_empty_when_no_match(tmp_path: Path):
    _write(tmp_path / "note.md", "Nothing relevant here.\n")

    result = search_notes(str(tmp_path), "xyz_not_there")

    assert result["total_found"] == 0
    assert result["results"] == []


def test_search_respects_limit(tmp_path: Path):
    for i in range(5):
        _write(tmp_path / f"note{i}.md", f"match {i}\n")

    result = search_notes(str(tmp_path), "match", limit=2)

    assert len(result["results"]) == 2
    assert result["total_found"] == 5


def test_search_respects_path_filter(tmp_path: Path):
    _write(tmp_path / "Projects" / "proj.md", "target content\n")
    _write(tmp_path / "Diary" / "diary.md", "target content\n")

    result = search_notes(str(tmp_path), "target", path_filter="Projects/")

    assert all(r["path"].startswith("Projects/") for r in result["results"])


def test_search_is_case_insensitive_by_default(tmp_path: Path):
    _write(tmp_path / "note.md", "Hello World\n")

    result = search_notes(str(tmp_path), "hello world")

    assert result["total_found"] == 1


def test_search_mode_is_regex(tmp_path: Path):
    _write(tmp_path / "note.md", "foo bar baz\n")

    result = search_notes(str(tmp_path), "foo.*baz")

    assert result["search_mode"] == "regex"
    assert result["total_found"] == 1


def test_search_caps_limit_to_max(tmp_path: Path):
    for i in range(30):
        _write(tmp_path / f"note{i}.md", "match\n")

    result = search_notes(str(tmp_path), "match", limit=100, search_limit_max=20)

    assert len(result["results"]) <= 20


def test_search_invalid_regex_falls_back_to_literal(tmp_path: Path):
    _write(tmp_path / "note.md", "See section [unclosed bracket here\n")

    result = search_notes(str(tmp_path), "[unclosed")

    assert result["total_found"] == 1


# ---------------------------------------------------------------------------
# list_all_tags
# ---------------------------------------------------------------------------


def test_list_tags_finds_frontmatter_tags(tmp_path: Path):
    _write(
        tmp_path / "note.md",
        "---\ntags:\n  - project\n  - gtd\n---\n\nBody.\n",
    )

    result = list_all_tags(str(tmp_path))

    tag_names = [t["tag"] for t in result["tags"]]
    assert "#project" in tag_names
    assert "#gtd" in tag_names


def test_list_tags_finds_inline_tags(tmp_path: Path):
    _write(tmp_path / "note.md", "Do the thing #context/pc today.\n")

    result = list_all_tags(str(tmp_path))

    tag_names = [t["tag"] for t in result["tags"]]
    assert "#context/pc" in tag_names


def test_list_tags_excludes_headings(tmp_path: Path):
    _write(tmp_path / "note.md", "# Not a tag\n\nThe tag #real_tag appears mid-sentence.\n")

    result = list_all_tags(str(tmp_path))

    tag_names = [t["tag"] for t in result["tags"]]
    assert "#Not" not in tag_names
    assert "#real_tag" in tag_names


def test_list_tags_excludes_code_blocks(tmp_path: Path):
    _write(tmp_path / "note.md", "```\n#code_tag\n```\n\nThe #real_tag is here.\n")

    result = list_all_tags(str(tmp_path))

    tag_names = [t["tag"] for t in result["tags"]]
    assert "#code_tag" not in tag_names
    assert "#real_tag" in tag_names


def test_list_tags_sorted_by_count_desc(tmp_path: Path):
    _write(tmp_path / "a.md", "---\ntags:\n  - common\n---\n\n#common extra\n")
    _write(tmp_path / "b.md", "---\ntags:\n  - common\n---\n\nBody.\n")
    _write(tmp_path / "c.md", "---\ntags:\n  - rare\n---\n\nBody.\n")

    result = list_all_tags(str(tmp_path))

    tags = result["tags"]
    assert tags[0]["tag"] == "#common"
    assert tags[0]["count"] > tags[-1]["count"]


def test_list_tags_total_unique_count(tmp_path: Path):
    _write(tmp_path / "note.md", "---\ntags:\n  - alpha\n  - beta\n---\n\nThe #gamma tag.\n")

    result = list_all_tags(str(tmp_path))

    assert result["total_unique"] == 3


# ---------------------------------------------------------------------------
# search_notes — include_frontmatter
# ---------------------------------------------------------------------------


def test_search_include_frontmatter_returns_fm_dict(tmp_path: Path):
    _write(
        tmp_path / "note.md",
        "---\nstatus: active\ntype: project\n---\n\nFind me here.\n",
    )

    result = search_notes(str(tmp_path), "Find me", include_frontmatter=True)

    assert result["total_found"] == 1
    r = result["results"][0]
    assert "frontmatter" in r
    assert r["frontmatter"]["status"] == "active"
    assert r["frontmatter"]["type"] == "project"


def test_search_include_frontmatter_false_omits_fm(tmp_path: Path):
    _write(tmp_path / "note.md", "---\nstatus: active\n---\n\nFind me here.\n")

    result = search_notes(str(tmp_path), "Find me", include_frontmatter=False)

    assert "frontmatter" not in result["results"][0]


def test_search_include_frontmatter_default_omits_fm(tmp_path: Path):
    _write(tmp_path / "note.md", "---\nstatus: active\n---\n\nFind me here.\n")

    result = search_notes(str(tmp_path), "Find me")

    assert "frontmatter" not in result["results"][0]

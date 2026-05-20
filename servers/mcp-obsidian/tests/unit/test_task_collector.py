from __future__ import annotations

from pathlib import Path

from mcp_obsidian.tasks.collector import collect_all_tasks


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# path filter
# ---------------------------------------------------------------------------


def test_collect_all_tasks_no_filter_returns_all(tmp_path: Path):
    _write(tmp_path / "Projects" / "alpha.md", "- [ ] Task A\n")
    _write(tmp_path / "Inbox" / "beta.md", "- [ ] Task B\n")

    result = collect_all_tasks(str(tmp_path))

    paths = {t["path"] for t in result["tasks"]}
    assert any(p.startswith("Projects") for p in paths)
    assert any(p.startswith("Inbox") for p in paths)


def test_collect_all_tasks_path_filter_scopes_to_file(tmp_path: Path):
    _write(tmp_path / "Projects" / "alpha.md", "- [ ] Task A\n")
    _write(tmp_path / "Inbox" / "beta.md", "- [ ] Task B\n")

    result = collect_all_tasks(str(tmp_path), path="Projects/alpha.md")

    assert result["total_tasks"] == 1
    assert result["tasks"][0]["path"] == "Projects/alpha.md"


def test_collect_all_tasks_path_filter_scopes_to_folder(tmp_path: Path):
    _write(tmp_path / "Projects" / "alpha.md", "- [ ] Task A\n")
    _write(tmp_path / "Projects" / "beta.md", "- [ ] Task B\n")
    _write(tmp_path / "Inbox" / "other.md", "- [ ] Task C\n")

    result = collect_all_tasks(str(tmp_path), path="Projects/")

    assert all(t["path"].startswith("Projects/") for t in result["tasks"])
    assert result["total_tasks"] == 2


def test_collect_all_tasks_path_filter_none_returns_all(tmp_path: Path):
    _write(tmp_path / "a.md", "- [ ] Task A\n")
    _write(tmp_path / "b.md", "- [ ] Task B\n")

    result = collect_all_tasks(str(tmp_path), path=None)

    assert result["total_tasks"] == 2

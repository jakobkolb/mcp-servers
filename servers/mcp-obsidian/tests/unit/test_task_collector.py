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


# ---------------------------------------------------------------------------
# dormant projects (completed / inactive)
# ---------------------------------------------------------------------------

_PROJECT_WITH_TASKS = """---
tags:
  - project
completed: {completed}
inactive: {inactive}
---
# A project

## Todo
- [ ] First task
- [ ] Second task
"""


def _project(path: Path, *, completed: bool = False, inactive: bool = False) -> None:
    _write(
        path,
        _PROJECT_WITH_TASKS.format(
            completed=str(completed).lower(), inactive=str(inactive).lower()
        ),
    )


def test_completed_project_contributes_no_tasks(tmp_path: Path):
    _project(tmp_path / "Projects" / "done.md", completed=True)

    result = collect_all_tasks(str(tmp_path))

    assert result["total_tasks"] == 0


def test_inactive_project_contributes_no_tasks(tmp_path: Path):
    _project(tmp_path / "Projects" / "paused.md", inactive=True)

    result = collect_all_tasks(str(tmp_path))

    assert result["total_tasks"] == 0


def test_completed_and_inactive_project_contributes_no_tasks(tmp_path: Path):
    _project(tmp_path / "Projects" / "both.md", completed=True, inactive=True)

    result = collect_all_tasks(str(tmp_path))

    assert result["total_tasks"] == 0


def test_dormant_project_is_not_reported_as_missing_a_next_action(tmp_path: Path):
    # It is not a live project, so it does not belong in the stalled-project audit
    # either -- it should be absent from the result entirely.
    _project(tmp_path / "Projects" / "done.md", completed=True)
    _project(tmp_path / "Projects" / "paused.md", inactive=True)

    result = collect_all_tasks(str(tmp_path))

    names = {p["name"] for p in result["projects_without_next_action"]}
    assert names == set()


def test_active_project_still_contributes_tasks(tmp_path: Path):
    _project(tmp_path / "Projects" / "live.md")

    result = collect_all_tasks(str(tmp_path))

    assert result["total_tasks"] == 1  # sequencing surfaces the first task of the section
    assert result["tasks"][0]["text"] == "First task"


def test_non_project_note_with_completed_frontmatter_still_contributes(tmp_path: Path):
    # The rule is about project notes. A plain note that happens to carry
    # completed: true is not a project and keeps its tasks.
    _write(
        tmp_path / "Inbox" / "note.md",
        "---\ncompleted: true\n---\n- [ ] Loose task\n",
    )

    result = collect_all_tasks(str(tmp_path))

    assert result["total_tasks"] == 1
    assert result["tasks"][0]["text"] == "Loose task"

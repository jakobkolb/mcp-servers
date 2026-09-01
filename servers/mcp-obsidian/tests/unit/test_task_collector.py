from __future__ import annotations

from datetime import date
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


def test_response_omits_unused_date_fields(tmp_path: Path):
    # 📅 and 🛫 drive nothing. raw_line still carries them verbatim, so no
    # information about historical tasks is lost by dropping the parsed fields.
    _write(tmp_path / "n.md", "- [ ] Old task 📅 2024-01-18 🛫 2024-01-01\n")

    result = collect_all_tasks(str(tmp_path))

    task = result["tasks"][0]
    assert "due_date" not in task
    assert "start_date" not in task
    assert "📅 2024-01-18" in task["raw_line"]


def test_unused_date_markers_are_still_stripped_from_text(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] Old task 📅 2024-01-18\n")

    result = collect_all_tasks(str(tmp_path))

    assert "📅" not in result["tasks"][0]["text"]


# ---------------------------------------------------------------------------
# availability (#80)
# ---------------------------------------------------------------------------

_TODAY = date(2026, 6, 15)

_DEFERRED_FIRST = """---
tags: [project]
---
## Todo
- [ ] Deferred next action ⏳ 2026-07-01
- [ ] Task behind it
"""


def test_deferred_next_action_silences_its_section(tmp_path: Path):
    # Strict sequencing: the section has exactly one next action and it is not
    # available yet, so the section contributes nothing. It must NOT promote the
    # task behind it -- that task depends on the deferred one.
    _write(tmp_path / "Projects" / "p.md", _DEFERRED_FIRST)

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert result["total_tasks"] == 0


def test_deferred_later_task_does_not_affect_the_next_action(tmp_path: Path):
    _write(
        tmp_path / "Projects" / "p.md",
        "---\ntags: [project]\n---\n## Todo\n- [ ] First\n- [ ] Second ⏳ 2026-07-01\n",
    )

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert result["total_tasks"] == 1
    assert result["tasks"][0]["text"] == "First"


def test_available_on_none_ignores_availability(tmp_path: Path):
    _write(tmp_path / "Projects" / "p.md", _DEFERRED_FIRST)

    result = collect_all_tasks(str(tmp_path), available_on=None)

    assert result["total_tasks"] == 1
    assert result["tasks"][0]["text"] == "Deferred next action"


def test_task_scheduled_exactly_on_available_on_is_available(tmp_path: Path):
    _write(
        tmp_path / "Projects" / "p.md",
        "---\ntags: [project]\n---\n## Todo\n- [ ] Due today ⏳ 2026-06-15\n",
    )

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert result["total_tasks"] == 1


def test_past_scheduled_date_is_available(tmp_path: Path):
    _write(
        tmp_path / "Projects" / "p.md",
        "---\ntags: [project]\n---\n## Todo\n- [ ] Overdue ⏳ 2026-01-01\n",
    )

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert result["total_tasks"] == 1


def test_future_start_date_does_not_defer(tmp_path: Path):
    # 🛫 is not part of this workflow; only ⏳ defers.
    _write(
        tmp_path / "Projects" / "p.md",
        "---\ntags: [project]\n---\n## Todo\n- [ ] Has a start date 🛫 2099-01-01\n",
    )

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert result["total_tasks"] == 1


def test_availability_applies_per_task_in_non_project_notes(tmp_path: Path):
    _write(tmp_path / "daily.md", "- [ ] Now\n- [ ] Later ⏳ 2026-07-01\n- [ ] Also now\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert {t["text"] for t in result["tasks"]} == {"Now", "Also now"}


def test_available_on_in_the_future_reveals_deferred_work(tmp_path: Path):
    _write(tmp_path / "Projects" / "p.md", _DEFERRED_FIRST)

    result = collect_all_tasks(str(tmp_path), available_on=date(2026, 7, 1))

    assert result["total_tasks"] == 1
    assert result["tasks"][0]["text"] == "Deferred next action"


# ---------------------------------------------------------------------------
# stalled-project audit (#81)
# ---------------------------------------------------------------------------


def _audit(result: dict) -> set[str]:
    return {p["name"] for p in result["projects_without_next_action"]}


def test_project_with_only_a_deferred_next_action_is_not_stalled(tmp_path: Path):
    # It has a next action; it just is not available yet. "No next action defined"
    # and "nothing to do right now" are different questions.
    _write(tmp_path / "Projects" / "deferred.md", _DEFERRED_FIRST)

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert result["total_tasks"] == 0
    assert _audit(result) == set()


def test_project_with_no_open_tasks_is_stalled(tmp_path: Path):
    _write(tmp_path / "Projects" / "empty.md", "---\ntags: [project]\n---\n## Todo\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert _audit(result) == {"empty"}


def test_project_with_all_tasks_completed_is_stalled(tmp_path: Path):
    _write(
        tmp_path / "Projects" / "finished.md",
        "---\ntags: [project]\n---\n## Todo\n- [x] Done ✅ 2026-01-01\n",
    )

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert _audit(result) == {"finished"}


def test_audit_is_stable_across_context_filters(tmp_path: Path):
    # The audit answers a question about the vault, not about the caller's filter.
    # Asking "what can I do at the PC" must not change which projects are stalled.
    _write(
        tmp_path / "Projects" / "live.md",
        "---\ntags: [project]\n---\n## Todo\n- [ ] Phone thing #context/phone\n",
    )
    _write(tmp_path / "Projects" / "empty.md", "---\ntags: [project]\n---\n## Todo\n")

    unfiltered = collect_all_tasks(str(tmp_path), available_on=_TODAY)
    by_pc = collect_all_tasks(str(tmp_path), context_tag="#context/pc", available_on=_TODAY)
    by_phone = collect_all_tasks(str(tmp_path), context_tag="#context/phone", available_on=_TODAY)

    assert _audit(unfiltered) == _audit(by_pc) == _audit(by_phone) == {"empty"}

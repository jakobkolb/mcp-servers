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
    by_pc = collect_all_tasks(str(tmp_path), tags=["#context/pc"], available_on=_TODAY)
    by_phone = collect_all_tasks(str(tmp_path), tags=["#context/phone"], available_on=_TODAY)

    assert _audit(unfiltered) == _audit(by_pc) == _audit(by_phone) == {"empty"}


# ---------------------------------------------------------------------------
# task provenance (#83)
# ---------------------------------------------------------------------------


def test_project_task_flag_true_for_project_notes(tmp_path: Path):
    _write(
        tmp_path / "Projects" / "p.md",
        "---\ntags: [project]\n---\n## Todo\n- [ ] In a project\n",
    )

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert result["tasks"][0]["project_task"] is True


def test_project_task_flag_false_for_other_notes(tmp_path: Path):
    _write(tmp_path / "daily.md", "- [ ] Loose task\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert result["tasks"][0]["project_task"] is False


def test_project_task_flag_does_not_depend_on_sequencing(tmp_path: Path):
    # The field says where the task came from, not whether sequencing ran.
    _write(
        tmp_path / "Projects" / "p.md",
        "---\ntags: [project]\n---\n## Todo\n- [ ] First\n- [ ] Second\n",
    )

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY, apply_sequencing=False)

    assert len(result["tasks"]) == 2
    assert all(t["project_task"] is True for t in result["tasks"])


def test_is_sequenced_field_is_gone(tmp_path: Path):
    _write(tmp_path / "daily.md", "- [ ] Loose task\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert "is_sequenced" not in result["tasks"][0]


# ---------------------------------------------------------------------------
# facets (#82)
# ---------------------------------------------------------------------------

_MIXED = """---
tags: [project]
---
## Todo
- [ ] Waiting and priority 🔼 #waiting-on #context/phone
"""


def test_priority_task_is_returned_by_both_of_its_facets(tmp_path: Path):
    # The old single-valued group put this task in "waiting" and it became
    # invisible to a priority query. Facets are not mutually exclusive.
    _write(tmp_path / "Projects" / "p.md", _MIXED)

    by_priority = collect_all_tasks(str(tmp_path), available_on=_TODAY, priority=True)
    by_waiting = collect_all_tasks(str(tmp_path), available_on=_TODAY, tags=["#waiting-on"])
    by_context = collect_all_tasks(str(tmp_path), available_on=_TODAY, tags=["#context/phone"])

    assert by_priority["total_tasks"] == 1
    assert by_waiting["total_tasks"] == 1
    assert by_context["total_tasks"] == 1


def test_someday_task_with_marker_is_still_priority(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] Someday but flagged 🔼 #someday\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY, priority=True)

    assert result["total_tasks"] == 1


def test_priority_inherited_from_project_frontmatter(tmp_path: Path):
    _write(
        tmp_path / "Projects" / "p.md",
        "---\ntags: [project, 🔼]\n---\n## Todo\n- [ ] No marker of its own\n",
    )

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY, priority=True)

    assert result["total_tasks"] == 1
    assert result["tasks"][0]["priority"] is True


def test_priority_false_excludes_priority_tasks(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] Flagged 🔼\n- [ ] Plain\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY, priority=False)

    assert {t["text"] for t in result["tasks"]} == {"Plain"}


def test_multi_context_task_matches_either_context(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] Both #context/pc #context/home\n")

    for tag in ("#context/pc", "#context/home"):
        result = collect_all_tasks(str(tmp_path), available_on=_TODAY, tags=[tag])
        assert result["total_tasks"] == 1, tag


def test_tags_filter_requires_all_of_them(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] Both #someday #context/pc\n- [ ] Only one #context/pc\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY, tags=["#someday", "#context/pc"])

    assert [t["text"].split(" #")[0] for t in result["tasks"]] == ["Both"]


def test_exclude_tags_removes_matching_tasks(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] Later #someday\n- [ ] Now #context/pc\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY, exclude_tags=["#someday"])

    assert [t["text"].split(" #")[0] for t in result["tasks"]] == ["Now"]


def test_untagged_facet(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] Bare\n- [ ] Tagged #context/pc\n")

    only = collect_all_tasks(str(tmp_path), available_on=_TODAY, untagged=True)
    without = collect_all_tasks(str(tmp_path), available_on=_TODAY, untagged=False)

    assert [t["text"] for t in only["tasks"]] == ["Bare"]
    assert [t["text"].split(" #")[0] for t in without["tasks"]] == ["Tagged"]


def test_unfiltered_returns_someday_and_waiting(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] A #someday\n- [ ] B #waiting-on\n- [ ] C\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert result["total_tasks"] == 3


def test_no_task_appears_twice_and_total_matches(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] Many facets 🔼 #someday #waiting-on #context/pc\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    keys = [(t["path"], t["line"]) for t in result["tasks"]]
    assert len(keys) == len(set(keys))
    assert result["total_tasks"] == len(result["tasks"]) == 1


def test_group_field_is_gone(tmp_path: Path):
    _write(tmp_path / "n.md", "- [ ] Task #context/pc\n")

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert "group" not in result["tasks"][0]


def test_priority_tasks_sort_first_then_oldest(tmp_path: Path):
    _write(
        tmp_path / "n.md",
        "- [ ] Old plain ➕2020-01-01\n- [ ] New priority 🔼 ➕2026-01-01\n",
    )

    result = collect_all_tasks(str(tmp_path), available_on=_TODAY)

    assert [t["text"] for t in result["tasks"]] == ["New priority", "Old plain"]

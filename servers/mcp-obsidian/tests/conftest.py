from pathlib import Path

import pytest

CONTENT = """---
title: Hello
created: 2026-04-15T15:39:59+02:00
completed: false
---
# Section Name
Body text.
"""


@pytest.fixture
def note() -> str:
    return CONTENT


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def note_with_frontmatter(tmp_vault: Path) -> Path:
    note_path = tmp_vault / "note_with_fm.md"
    note_path.write_text(
        "---\n"
        "title: Test Note\n"
        "completed: false\n"
        "tags:\n"
        "  - project\n"
        "  - gtd\n"
        "---\n"
        "\n"
        "# Test Note\n"
        "\n"
        "Body content here.\n",
        encoding="utf-8",
    )
    return note_path


@pytest.fixture
def note_without_frontmatter(tmp_vault: Path) -> Path:
    note_path = tmp_vault / "plain_note.md"
    note_path.write_text("# Plain Note\n\nJust a body.\n", encoding="utf-8")
    return note_path

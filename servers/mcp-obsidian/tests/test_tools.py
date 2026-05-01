import os

import pytest

os.environ.setdefault("OBSIDIAN_API_KEY", "test-key")

from mcp_obsidian import tools  # noqa: E402
from mcp_obsidian.tools import (  # noqa: E402
    AppendContentToolHandler,
    BatchGetFileContentsToolHandler,
    ComplexSearchToolHandler,
    DeleteFileToolHandler,
    GetFileContentsToolHandler,
    ListFilesInDirToolHandler,
    ListFilesInVaultToolHandler,
    PatchContentToolHandler,
    PeriodicNotesToolHandler,
    PutContentToolHandler,
    RecentChangesToolHandler,
    RecentPeriodicNotesToolHandler,
    SearchToolHandler,
)


def _text(result: list) -> str:
    return result[0].text


def test_list_files_in_vault(mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(tools, "_api", return_value=mocker.MagicMock(
        list_files_in_vault=lambda: ["a.md", "b.md"]
    ))
    result = ListFilesInVaultToolHandler().run_tool({})
    assert "a.md" in _text(result)


def test_list_files_in_dir_missing_arg() -> None:
    with pytest.raises(RuntimeError, match="dirpath"):
        ListFilesInDirToolHandler().run_tool({})


def test_list_files_in_dir(mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(tools, "_api", return_value=mocker.MagicMock(
        list_files_in_dir=lambda p: ["note.md"]
    ))
    result = ListFilesInDirToolHandler().run_tool({"dirpath": "Projects"})
    assert "note.md" in _text(result)


def test_get_file_contents_missing_arg() -> None:
    with pytest.raises(RuntimeError, match="filepath"):
        GetFileContentsToolHandler().run_tool({})


def test_get_file_contents(mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(tools, "_api", return_value=mocker.MagicMock(
        get_file_contents=lambda p: "# Hello"
    ))
    result = GetFileContentsToolHandler().run_tool({"filepath": "note.md"})
    assert "Hello" in _text(result)


def test_batch_get_file_contents_missing_arg() -> None:
    with pytest.raises(RuntimeError, match="filepaths"):
        BatchGetFileContentsToolHandler().run_tool({})


def test_batch_get_file_contents(mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(tools, "_api", return_value=mocker.MagicMock(
        get_batch_file_contents=lambda fps: "# a.md\n\ncontent"
    ))
    result = BatchGetFileContentsToolHandler().run_tool({"filepaths": ["a.md"]})
    assert "a.md" in _text(result)


def test_search_missing_arg() -> None:
    with pytest.raises(RuntimeError, match="query"):
        SearchToolHandler().run_tool({})


def test_search(mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(tools, "_api", return_value=mocker.MagicMock(
        search=lambda q, ctx: [{"filename": "note.md", "score": 1.0, "matches": []}]
    ))
    result = SearchToolHandler().run_tool({"query": "hello"})
    assert "note.md" in _text(result)


def test_complex_search_missing_arg() -> None:
    with pytest.raises(RuntimeError, match="query"):
        ComplexSearchToolHandler().run_tool({})


def test_complex_search(mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(tools, "_api", return_value=mocker.MagicMock(
        search_json=lambda q: [{"path": "note.md"}]
    ))
    result = ComplexSearchToolHandler().run_tool({"query": {"glob": ["*.md", {"var": "path"}]}})
    assert "note.md" in _text(result)


def test_append_content_missing_args() -> None:
    with pytest.raises(RuntimeError):
        AppendContentToolHandler().run_tool({"filepath": "note.md"})


def test_append_content(mocker: pytest.MonkeyPatch) -> None:
    mock_api = mocker.MagicMock()
    mocker.patch.object(tools, "_api", return_value=mock_api)
    result = AppendContentToolHandler().run_tool({"filepath": "note.md", "content": "text"})
    mock_api.append_content.assert_called_once_with("note.md", "text")
    assert "Successfully" in _text(result)


def test_patch_content_missing_args() -> None:
    with pytest.raises(RuntimeError):
        PatchContentToolHandler().run_tool({"filepath": "note.md"})


def test_patch_content(mocker: pytest.MonkeyPatch) -> None:
    mock_api = mocker.MagicMock()
    mocker.patch.object(tools, "_api", return_value=mock_api)
    args = {
        "filepath": "note.md",
        "operation": "append",
        "target_type": "heading",
        "target": "## Tasks",
        "content": "- new item",
    }
    result = PatchContentToolHandler().run_tool(args)
    mock_api.patch_content.assert_called_once()
    assert "Successfully" in _text(result)


def test_put_content(mocker: pytest.MonkeyPatch) -> None:
    mock_api = mocker.MagicMock()
    mocker.patch.object(tools, "_api", return_value=mock_api)
    result = PutContentToolHandler().run_tool({"filepath": "note.md", "content": "# New"})
    mock_api.put_content.assert_called_once_with("note.md", "# New")
    assert "Successfully" in _text(result)


def test_delete_file_requires_confirm() -> None:
    with pytest.raises(RuntimeError, match="confirm"):
        DeleteFileToolHandler().run_tool({"filepath": "note.md", "confirm": False})


def test_delete_file(mocker: pytest.MonkeyPatch) -> None:
    mock_api = mocker.MagicMock()
    mocker.patch.object(tools, "_api", return_value=mock_api)
    result = DeleteFileToolHandler().run_tool({"filepath": "note.md", "confirm": True})
    mock_api.delete_file.assert_called_once_with("note.md")
    assert "Successfully" in _text(result)


def test_periodic_note_invalid_period() -> None:
    with pytest.raises(RuntimeError, match="Invalid period"):
        PeriodicNotesToolHandler().run_tool({"period": "hourly"})


def test_periodic_note(mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(tools, "_api", return_value=mocker.MagicMock(
        get_periodic_note=lambda p, t: "# Daily"
    ))
    result = PeriodicNotesToolHandler().run_tool({"period": "daily"})
    assert "Daily" in _text(result)


def test_recent_periodic_notes_invalid_period() -> None:
    with pytest.raises(RuntimeError, match="Invalid period"):
        RecentPeriodicNotesToolHandler().run_tool({"period": "hourly"})


def test_recent_periodic_notes(mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(tools, "_api", return_value=mocker.MagicMock(
        get_recent_periodic_notes=lambda p, l, c: [{"path": "daily.md"}]
    ))
    result = RecentPeriodicNotesToolHandler().run_tool({"period": "daily", "limit": 3})
    assert "daily.md" in _text(result)


def test_recent_changes(mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(tools, "_api", return_value=mocker.MagicMock(
        get_recent_changes=lambda l, d: {"results": []}
    ))
    result = RecentChangesToolHandler().run_tool({"limit": 5, "days": 7})
    assert "results" in _text(result)


def test_all_handlers_registered() -> None:
    assert len(tools.ALL_HANDLERS) == 13


def test_all_handlers_have_descriptions() -> None:
    for handler in tools.ALL_HANDLERS:
        desc = handler.get_tool_description()
        assert desc.name
        assert desc.description
        assert desc.inputSchema

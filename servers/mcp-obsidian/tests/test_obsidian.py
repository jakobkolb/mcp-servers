import os

import pytest
import requests

os.environ.setdefault("OBSIDIAN_API_KEY", "test-key")

from mcp_obsidian.obsidian import Obsidian  # noqa: E402


@pytest.fixture
def api() -> Obsidian:
    return Obsidian(api_key="test-key", host="127.0.0.1", port=27124)


def test_base_url(api: Obsidian) -> None:
    assert api.get_base_url() == "https://127.0.0.1:27124"


def test_base_url_http() -> None:
    api = Obsidian(api_key="k", protocol="http", host="localhost", port=8080)
    assert api.get_base_url() == "http://localhost:8080"


def test_get_headers(api: Obsidian) -> None:
    assert api._get_headers() == {"Authorization": "Bearer test-key"}


def test_safe_call_http_error(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_resp = mocker.MagicMock()
    mock_resp.content = b'{"errorCode": 404, "message": "Not found"}'
    mock_resp.json.return_value = {"errorCode": 404, "message": "Not found"}
    err = requests.HTTPError(response=mock_resp)

    with pytest.raises(Exception, match="Error 404: Not found"):
        api._safe_call(lambda: (_ for _ in ()).throw(err))


def test_safe_call_request_exception(api: Obsidian) -> None:
    def raise_conn():
        raise requests.exceptions.ConnectionError("refused")

    with pytest.raises(Exception, match="Request failed"):
        api._safe_call(raise_conn)


def test_list_files_in_vault(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_get = mocker.patch("requests.get")
    mock_get.return_value.json.return_value = {"files": ["note.md", "folder/"]}
    mock_get.return_value.raise_for_status = lambda: None

    result = api.list_files_in_vault()
    assert result == ["note.md", "folder/"]
    mock_get.assert_called_once()


def test_list_files_in_dir(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_get = mocker.patch("requests.get")
    mock_get.return_value.json.return_value = {"files": ["note.md"]}
    mock_get.return_value.raise_for_status = lambda: None

    result = api.list_files_in_dir("Projects")
    assert result == ["note.md"]
    assert "Projects" in mock_get.call_args[0][0]


def test_get_file_contents(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_get = mocker.patch("requests.get")
    mock_get.return_value.text = "# My Note\n\nHello."
    mock_get.return_value.raise_for_status = lambda: None

    result = api.get_file_contents("note.md")
    assert result == "# My Note\n\nHello."


def test_get_batch_file_contents(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(api, "get_file_contents", side_effect=["Content A", "Content B"])
    result = api.get_batch_file_contents(["a.md", "b.md"])
    assert "# a.md" in result
    assert "Content A" in result
    assert "# b.md" in result
    assert "Content B" in result


def test_get_batch_file_contents_partial_error(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mocker.patch.object(api, "get_file_contents", side_effect=[Exception("not found"), "Content B"])
    result = api.get_batch_file_contents(["missing.md", "b.md"])
    assert "Error reading file" in result
    assert "Content B" in result


def test_append_content(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_post = mocker.patch("requests.post")
    mock_post.return_value.raise_for_status = lambda: None

    api.append_content("note.md", "new text")
    mock_post.assert_called_once()
    assert "note.md" in mock_post.call_args[0][0]


def test_put_content(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_put = mocker.patch("requests.put")
    mock_put.return_value.raise_for_status = lambda: None

    api.put_content("note.md", "# New content")
    mock_put.assert_called_once()


def test_delete_file(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_delete = mocker.patch("requests.delete")
    mock_delete.return_value.raise_for_status = lambda: None

    api.delete_file("note.md")
    mock_delete.assert_called_once()
    assert "note.md" in mock_delete.call_args[0][0]


def test_search(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_post = mocker.patch("requests.post")
    mock_post.return_value.json.return_value = [
        {"filename": "note.md", "score": 1.0, "matches": []}
    ]
    mock_post.return_value.raise_for_status = lambda: None

    result = api.search("hello", context_length=50)
    assert result[0]["filename"] == "note.md"
    assert mock_post.call_args[1]["params"]["contextLength"] == 50


def test_search_json(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_post = mocker.patch("requests.post")
    mock_post.return_value.json.return_value = [{"path": "note.md"}]
    mock_post.return_value.raise_for_status = lambda: None

    query = {"glob": ["*.md", {"var": "path"}]}
    result = api.search_json(query)
    assert result[0]["path"] == "note.md"
    assert "application/vnd.olrapi.jsonlogic" in mock_post.call_args[1]["headers"]["Content-Type"]


def test_get_periodic_note_content(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_get = mocker.patch("requests.get")
    mock_get.return_value.text = "# Daily note"
    mock_get.return_value.raise_for_status = lambda: None

    result = api.get_periodic_note("daily")
    assert result == "# Daily note"
    assert "periodic/daily" in mock_get.call_args[0][0]


def test_get_periodic_note_metadata(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_get = mocker.patch("requests.get")
    mock_get.return_value.text = '{"path": "daily.md"}'
    mock_get.return_value.raise_for_status = lambda: None

    api.get_periodic_note("daily", type="metadata")
    headers = mock_get.call_args[1]["headers"]
    assert "application/vnd.olrapi.note+json" in headers.get("Accept", "")


def test_get_recent_changes(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_post = mocker.patch("requests.post")
    mock_post.return_value.json.return_value = {"results": []}
    mock_post.return_value.raise_for_status = lambda: None

    api.get_recent_changes(limit=5, days=7)
    sent_data = mock_post.call_args[1]["data"].decode()
    assert "LIMIT 5" in sent_data
    assert "dur(7 days)" in sent_data


def test_get_recent_periodic_notes_daily(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_post = mocker.patch("requests.post")
    mock_post.return_value.json.return_value = [{"filename": "2026-05-01.md"}]
    mock_post.return_value.raise_for_status = lambda: None

    result = api.get_recent_periodic_notes("daily", limit=3)
    sent_data = mock_post.call_args[1]["data"].decode()
    assert "file.day" in sent_data
    assert "LIMIT 3" in sent_data
    assert result[0]["filename"] == "2026-05-01.md"


def test_get_recent_periodic_notes_weekly(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_get = mocker.patch("requests.get")
    mock_get.return_value.json.return_value = {"path": "Journals/Weekly/2026-W18.md"}
    mock_get.return_value.raise_for_status = lambda: None

    mock_post = mocker.patch("requests.post")
    mock_post.return_value.json.return_value = [{"filename": "2026-W18.md"}]
    mock_post.return_value.raise_for_status = lambda: None

    result = api.get_recent_periodic_notes("weekly", limit=2)
    dql = mock_post.call_args[1]["data"].decode()
    assert "Journals/Weekly" in dql
    assert "LIMIT 2" in dql
    assert result[0]["filename"] == "2026-W18.md"


def test_patch_content_strips_block_caret(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_patch = mocker.patch("requests.patch")
    mock_patch.return_value.raise_for_status = lambda: None

    api.patch_content("note.md", "replace", "block", "^myblock", "new content")
    headers = mock_patch.call_args[1]["headers"]
    # ^ should be stripped before URL-encoding
    assert headers["Target"] == "myblock"


def test_patch_content_heading_unchanged(api: Obsidian, mocker: pytest.MonkeyPatch) -> None:
    mock_patch = mocker.patch("requests.patch")
    mock_patch.return_value.raise_for_status = lambda: None

    api.patch_content("note.md", "append", "heading", "## Tasks", "- item")
    headers = mock_patch.call_args[1]["headers"]
    assert headers["Target"] == "%23%23%20Tasks"

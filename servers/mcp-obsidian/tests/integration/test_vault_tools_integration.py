from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Vault fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def task_vault(tmp_path_factory: pytest.TempPathFactory) -> Path:
    vault = tmp_path_factory.mktemp("task_vault")

    # daily note with tasks using several context tags
    (vault / "daily").mkdir()
    (vault / "daily" / "2026-05-13.md").write_text(
        textwrap.dedent(
            """\
            # 2026-05-13

            ## Tasks

            - [ ] Call the school about the trip #context/kids 📅 2026-05-13
            - [ ] Buy groceries #context/home
            - [ ] Call dentist #context/phone
            - [ ] Review PR on laptop #context/pc
            - [ ] Pick up kids from practice #context/kids

            ## Morgens - 2 Minuten Check In

            - [ ] This should be excluded #context/kids
            """
        ),
        encoding="utf-8",
    )

    # project note with sequenced tasks
    (vault / "Projects").mkdir()
    (vault / "Projects" / "Family Trip.md").write_text(
        textwrap.dedent(
            """\
            ---
            tags:
              - project
            ---

            # Family Trip

            ## Planning

            - [ ] Book hotel #context/kids
            - [ ] Check passport expiry #context/kids
            """
        ),
        encoding="utf-8",
    )

    # inbox with a few tasks
    (vault / "inbox.md").write_text(
        textwrap.dedent(
            """\
            # Inbox

            - [ ] Fix CI pipeline #context/pc ⏳ 2026-05-14
            - [ ] Read article #context/pc
            """
        ),
        encoding="utf-8",
    )

    return vault


# ---------------------------------------------------------------------------
# MCP client
# ---------------------------------------------------------------------------


class StdioMCPClient:
    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self._proc: subprocess.Popen[str] | None = None
        self._msg_id = 0

    def start(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_obsidian.main"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "VAULT_PATH": self.vault_path,
                "MCP_TRANSPORT": "stdio",
                "LOG_LEVEL": "WARNING",
            },
            text=True,
            bufsize=1,
        )

    def stop(self) -> None:
        if self._proc:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)

    def _send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError("Client is not started")
        self._msg_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._msg_id,
            "method": method,
            "params": params,
        }
        self._proc.stdin.write(json.dumps(request) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            stderr = self._proc.stderr.read() if self._proc.stderr else ""
            raise RuntimeError(f"Server exited without a response. stderr:\n{stderr}")
        return json.loads(line)

    def initialize(self) -> dict[str, Any]:
        return self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0.1"},
            },
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._send("tools/call", {"name": name, "arguments": arguments})


@pytest.fixture(scope="module")
def mcp_client(task_vault: Path):
    client = StdioMCPClient(str(task_vault))
    client.start()
    client.initialize()
    yield client
    client.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def tool_payload(response: dict[str, Any]) -> Any:
    assert not response["result"].get("isError"), response["result"]["content"][0]["text"]
    return json.loads(response["result"]["content"][0]["text"])


# ---------------------------------------------------------------------------
# TestContextTagRename
# ---------------------------------------------------------------------------


class TestContextTagRename:
    """Rename #context/kids → #context/children across all task files."""

    def test_finds_kids_tasks_before_rename(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool("get_tasks", {"context_tag": "#context/kids"})
        data = tool_payload(resp)
        assert data["total_tasks"] > 0, "Expected at least one #context/kids task before rename"

    def test_rename_tag_via_patch_note(self, mcp_client: StdioMCPClient, task_vault: Path):
        resp = mcp_client.call_tool(
            "get_tasks", {"context_tag": "#context/kids", "include_someday": True}
        )
        data = tool_payload(resp)

        affected_paths: set[str] = {task["path"] for task in data["tasks"]}

        assert affected_paths, "No files found with #context/kids tasks"

        for path in affected_paths:
            patch_resp = mcp_client.call_tool(
                "patch_note",
                {
                    "path": path,
                    "old_string": "#context/kids",
                    "new_string": "#context/children",
                    "replace_all": True,
                },
            )
            assert not patch_resp["result"].get("isError"), (
                f"patch_note failed on {path}: {patch_resp['result']['content'][0]['text']}"
            )

    def test_no_kids_tasks_after_rename(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool(
            "get_tasks", {"context_tag": "#context/kids", "include_someday": True}
        )
        data = tool_payload(resp)
        assert data["total_tasks"] == 0, (
            f"Expected 0 #context/kids tasks after rename, got {data['total_tasks']}"
        )

    def test_children_tasks_exist_after_rename(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool(
            "get_tasks", {"context_tag": "#context/children", "include_someday": True}
        )
        data = tool_payload(resp)
        assert data["total_tasks"] > 0, "Expected #context/children tasks to exist after rename"

    def test_file_content_reflects_rename(self, task_vault: Path):
        daily = (task_vault / "daily" / "2026-05-13.md").read_text(encoding="utf-8")
        assert "#context/kids" not in daily
        assert "#context/children" in daily

        project = (task_vault / "Projects" / "Family Trip.md").read_text(encoding="utf-8")
        assert "#context/kids" not in project
        assert "#context/children" in project


# ---------------------------------------------------------------------------
# TestCompleteTaskWorkflow
# ---------------------------------------------------------------------------


class TestCompleteTaskWorkflow:
    """Complete a #context/phone task and verify it disappears from open tasks."""

    def test_complete_phone_task(self, mcp_client: StdioMCPClient, task_vault: Path):
        resp = mcp_client.call_tool("get_tasks", {"context_tag": "#context/phone"})
        data = tool_payload(resp)
        assert data["total_tasks"] >= 1, "Need at least one #context/phone task"

        phone_task = data["tasks"][0]

        path = phone_task["path"]
        line = phone_task["line"]

        complete_resp = mcp_client.call_tool(
            "complete_task",
            {"path": path, "line": line, "done_date": "2026-05-13"},
        )
        assert not complete_resp["result"].get("isError"), complete_resp["result"]["content"][0][
            "text"
        ]

    def test_phone_task_gone_from_open_tasks(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool("get_tasks", {"context_tag": "#context/phone"})
        data = tool_payload(resp)
        assert data["total_tasks"] == 0, "Phone task should be gone after completion"

    def test_completed_task_has_checkmark_in_file(self, task_vault: Path):
        daily = (task_vault / "daily" / "2026-05-13.md").read_text(encoding="utf-8")
        assert "- [x]" in daily
        assert "✅" in daily
        assert "2026-05-13" in daily


# ---------------------------------------------------------------------------
# TestDeferTaskWorkflow
# ---------------------------------------------------------------------------


class TestDeferTaskWorkflow:
    """Schedule a #context/pc task to the far future and verify it's hidden."""

    def test_pc_task_visible_before_defer(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool(
            "get_tasks",
            {"context_tag": "#context/pc", "hide_future_scheduled": False},
        )
        data = tool_payload(resp)
        assert data["total_tasks"] >= 1, "Need at least one #context/pc task"

    def test_defer_pc_task_to_future(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool(
            "get_tasks",
            {"context_tag": "#context/pc", "hide_future_scheduled": False},
        )
        data = tool_payload(resp)

        target = next((t for t in data["tasks"] if not t.get("scheduled_date")), None)

        assert target is not None, "Need a #context/pc task without a scheduled date"
        TestDeferTaskWorkflow._deferred_path = target["path"]
        TestDeferTaskWorkflow._deferred_line = target["line"]

        defer_resp = mcp_client.call_tool(
            "set_task_date",
            {
                "path": target["path"],
                "line": target["line"],
                "date_type": "scheduled",
                "date": "2099-12-31",
            },
        )
        assert not defer_resp["result"].get("isError"), defer_resp["result"]["content"][0]["text"]

    def test_deferred_task_hidden_with_flag(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool(
            "get_tasks",
            {"context_tag": "#context/pc", "hide_future_scheduled": True},
        )
        data = tool_payload(resp)

        deferred_path = getattr(TestDeferTaskWorkflow, "_deferred_path", None)
        deferred_line = getattr(TestDeferTaskWorkflow, "_deferred_line", None)

        for task in data["tasks"]:
            assert not (task["path"] == deferred_path and task["line"] == deferred_line), (
                "Deferred task should be hidden when hide_future_scheduled=True"
            )

    def test_deferred_task_visible_without_flag(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool(
            "get_tasks",
            {"context_tag": "#context/pc", "hide_future_scheduled": False},
        )
        data = tool_payload(resp)

        deferred_path = getattr(TestDeferTaskWorkflow, "_deferred_path", None)
        deferred_line = getattr(TestDeferTaskWorkflow, "_deferred_line", None)

        found = any(
            t["path"] == deferred_path and t["line"] == deferred_line for t in data["tasks"]
        )
        assert found, "Deferred task should appear when hide_future_scheduled=False"


# ---------------------------------------------------------------------------
# TestWriteSearchReadWorkflow
# ---------------------------------------------------------------------------


class TestWriteSearchReadWorkflow:
    """Write a note, search for unique content, read it back."""

    _NOTE_PATH = "search_test_note.md"
    _UNIQUE_PHRASE = "xyzzy-integration-test-unique-phrase-42"

    def test_write_note(self, mcp_client: StdioMCPClient):
        content = f"# Search Test\n\nThis note contains {self._UNIQUE_PHRASE} for search.\n"
        resp = mcp_client.call_tool(
            "write_note",
            {"path": self._NOTE_PATH, "content": content, "mode": "overwrite"},
        )
        assert not resp["result"].get("isError"), resp["result"]["content"][0]["text"]

    def test_search_finds_written_note(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool("search_notes", {"query": self._UNIQUE_PHRASE})
        data = tool_payload(resp)

        paths = [r["path"] for r in data["results"]]
        assert self._NOTE_PATH in paths, f"{self._NOTE_PATH!r} not found in search results: {paths}"

    def test_read_note_returns_content(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool("read_note", {"path": self._NOTE_PATH})
        data = tool_payload(resp)

        assert self._UNIQUE_PHRASE in data["content"]
        assert data["path"] == self._NOTE_PATH

    def test_search_result_includes_matching_snippet(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool("search_notes", {"query": self._UNIQUE_PHRASE})
        data = tool_payload(resp)

        result = next((r for r in data["results"] if r["path"] == self._NOTE_PATH), None)
        assert result is not None
        assert self._UNIQUE_PHRASE in result["snippet"]


# ---------------------------------------------------------------------------
# TestAddTaskWorkflow
# ---------------------------------------------------------------------------


class TestAddTaskWorkflow:
    """Add a task to inbox and verify it appears in get_tasks."""

    _TASK_TEXT = "integration test task xyzzy"

    def test_add_task_to_inbox(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool(
            "add_task",
            {
                "path": "inbox.md",
                "text": self._TASK_TEXT,
                "tags": ["#context/test"],
                "stamp_created": False,
            },
        )
        assert not resp["result"].get("isError"), resp["result"]["content"][0]["text"]

    def test_added_task_appears_in_get_tasks(self, mcp_client: StdioMCPClient):
        resp = mcp_client.call_tool("get_tasks", {"context_tag": "#context/test"})
        data = tool_payload(resp)

        found = any(self._TASK_TEXT in t["text"] for t in data["tasks"])
        assert found, f"Task {self._TASK_TEXT!r} not found in get_tasks after add_task"

    def test_added_task_in_inbox_file(self, task_vault: Path):
        content = (task_vault / "inbox.md").read_text(encoding="utf-8")
        assert self._TASK_TEXT in content
        assert "#context/test" in content

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(scope="module")
def minimal_vault(tmp_path_factory: pytest.TempPathFactory) -> Path:
    vault = tmp_path_factory.mktemp("vault")
    (vault / "simple.md").write_text(
        "# Simple Note\n\nJust some plain content.\n",
        encoding="utf-8",
    )
    (vault / "with_fm.md").write_text(
        textwrap.dedent(
            """\
            ---
            title: Note With Frontmatter
            completed: false
            tags:
              - project
              - gtd
            ---

            ## Body

            This is the body of the note.
            """
        ),
        encoding="utf-8",
    )
    (vault / "Getting things done" / "Projects").mkdir(parents=True)
    (vault / "Getting things done" / "Projects" / "LiZu.md").write_text(
        "---\ntags:\n  - project\n---\n\n- [ ] Follow up with Julian\n",
        encoding="utf-8",
    )
    return vault


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

    def list_tools(self) -> dict[str, Any]:
        return self._send("tools/list", {})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._send("tools/call", {"name": name, "arguments": arguments})


@pytest.fixture(scope="module")
def mcp_client(minimal_vault: Path):
    client = StdioMCPClient(str(minimal_vault))
    client.start()
    client.initialize()
    yield client
    client.stop()


def test_server_lists_read_note_tool(mcp_client: StdioMCPClient):
    response = mcp_client.list_tools()

    names = [tool["name"] for tool in response["result"]["tools"]]

    assert "read_note" in names


def test_reads_simple_note(mcp_client: StdioMCPClient):
    response = mcp_client.call_tool("read_note", {"path": "simple.md"})
    payload = json.loads(response["result"]["content"][0]["text"])

    assert not response["result"].get("isError")
    assert payload["path"] == "simple.md"
    assert payload["frontmatter"] == {}
    assert "Just some plain content." in payload["content"]


def test_reads_note_with_frontmatter(mcp_client: StdioMCPClient):
    response = mcp_client.call_tool("read_note", {"path": "with_fm.md"})
    payload = json.loads(response["result"]["content"][0]["text"])

    assert not response["result"].get("isError")
    assert payload["frontmatter"]["title"] == "Note With Frontmatter"
    assert payload["frontmatter"]["completed"] is False
    assert "This is the body of the note." in payload["content"]


def test_reads_note_in_subdirectory(mcp_client: StdioMCPClient):
    response = mcp_client.call_tool(
        "read_note",
        {"path": "Getting things done/Projects/LiZu.md"},
    )
    payload = json.loads(response["result"]["content"][0]["text"])

    assert not response["result"].get("isError")
    assert "project" in payload["frontmatter"]["tags"]
    assert "Follow up with Julian" in payload["content"]


def test_returns_error_for_missing_note(mcp_client: StdioMCPClient):
    response = mcp_client.call_tool("read_note", {"path": "does_not_exist.md"})

    assert response["result"].get("isError") is True
    assert "NOT_FOUND" in response["result"]["content"][0]["text"]


def test_returns_error_for_path_traversal(mcp_client: StdioMCPClient):
    response = mcp_client.call_tool("read_note", {"path": "../outside.md"})

    assert response["result"].get("isError") is True
    assert "INVALID_PATH" in response["result"]["content"][0]["text"]


def test_returns_error_for_non_markdown_file(mcp_client: StdioMCPClient):
    (Path(mcp_client.vault_path) / "data.txt").write_text("some text", encoding="utf-8")

    response = mcp_client.call_tool("read_note", {"path": "data.txt"})

    assert response["result"].get("isError") is True
    assert "NOT_A_NOTE" in response["result"]["content"][0]["text"]

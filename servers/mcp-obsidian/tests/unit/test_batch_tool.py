from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from mcp_obsidian.tools.batch import execute_batch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_handler(return_value: dict) -> AsyncMock:
    return AsyncMock(return_value=return_value)


def _failing_handler(exc: Exception) -> AsyncMock:
    m = AsyncMock(side_effect=exc)
    return m


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_unknown_tool_returns_validation_failed():
    result = await execute_batch(
        invocations=[{"tool": "nonexistent_tool", "arguments": {}}],
        handlers={},
        tools_by_name={},
    )
    assert result["status"] == "validation_failed"
    assert result["errors"][0]["index"] == 0
    assert "nonexistent_tool" in result["errors"][0]["error"]


@pytest.mark.asyncio
async def test_batch_missing_required_field_returns_validation_failed():
    from mcp.types import Tool

    tool = Tool(
        name="dummy",
        description="",
        inputSchema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    result = await execute_batch(
        invocations=[{"tool": "dummy", "arguments": {}}],
        handlers={"dummy": _ok_handler({"ok": True})},
        tools_by_name={"dummy": tool},
    )
    assert result["status"] == "validation_failed"
    assert result["errors"][0]["index"] == 0


@pytest.mark.asyncio
async def test_batch_validation_reports_all_bad_invocations():
    result = await execute_batch(
        invocations=[
            {"tool": "bad_a", "arguments": {}},
            {"tool": "bad_b", "arguments": {}},
        ],
        handlers={},
        tools_by_name={},
    )
    assert result["status"] == "validation_failed"
    assert len(result["errors"]) == 2
    assert result["results"] == []


@pytest.mark.asyncio
async def test_batch_no_side_effects_on_validation_failure():
    from mcp.types import Tool

    tool = Tool(
        name="dummy",
        description="",
        inputSchema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    handler = _ok_handler({"ok": True})
    await execute_batch(
        invocations=[
            {"tool": "dummy", "arguments": {"path": "a.md"}},  # valid
            {"tool": "unknown", "arguments": {}},  # invalid
        ],
        handlers={"dummy": handler},
        tools_by_name={"dummy": tool},
    )
    handler.assert_not_called()


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_executes_valid_invocations():
    from mcp.types import Tool

    tool = Tool(
        name="dummy",
        description="",
        inputSchema={"type": "object", "properties": {}},
    )
    handler = _ok_handler({"result": "done"})
    result = await execute_batch(
        invocations=[{"tool": "dummy", "arguments": {}}],
        handlers={"dummy": handler},
        tools_by_name={"dummy": tool},
    )
    assert result["status"] == "ok"
    assert result["results"][0]["result"] == {"result": "done"}
    assert result["results"][0]["error"] is None


@pytest.mark.asyncio
async def test_batch_returns_error_per_invocation_on_runtime_failure():
    from mcp.types import Tool

    tool = Tool(
        name="dummy",
        description="",
        inputSchema={"type": "object", "properties": {}},
    )
    handler = _failing_handler(ValueError("boom"))
    result = await execute_batch(
        invocations=[{"tool": "dummy", "arguments": {}}],
        handlers={"dummy": handler},
        tools_by_name={"dummy": tool},
    )
    assert result["status"] == "ok"
    assert result["results"][0]["result"] is None
    assert "boom" in result["results"][0]["error"]


@pytest.mark.asyncio
async def test_batch_result_indices_match_submission_order():
    from mcp.types import Tool

    tool = Tool(
        name="dummy",
        description="",
        inputSchema={"type": "object", "properties": {}},
    )
    handlers = {"dummy": AsyncMock(side_effect=[{"n": 0}, {"n": 1}, {"n": 2}])}
    result = await execute_batch(
        invocations=[
            {"tool": "dummy", "arguments": {}},
            {"tool": "dummy", "arguments": {}},
            {"tool": "dummy", "arguments": {}},
        ],
        handlers=handlers,
        tools_by_name={"dummy": tool},
    )
    assert [r["index"] for r in result["results"]] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Path-grouping / race condition prevention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_same_path_executed_sequentially():
    """Operations on the same path must run in submission order."""
    from mcp.types import Tool

    tool = Tool(
        name="write",
        description="",
        inputSchema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    )
    call_order: list[int] = []

    async def handler_a(args: dict) -> dict:
        call_order.append(0)
        return {"n": 0}

    async def handler_b(args: dict) -> dict:
        call_order.append(1)
        return {"n": 1}

    # Two invocations of same tool/path
    result = await execute_batch(
        invocations=[
            {"tool": "write", "arguments": {"path": "note.md"}},
            {"tool": "write", "arguments": {"path": "note.md"}},
        ],
        handlers={"write": AsyncMock(side_effect=[{"n": 0}, {"n": 1}])},
        tools_by_name={"write": tool},
    )
    assert result["status"] == "ok"
    assert len(result["results"]) == 2


@pytest.mark.asyncio
async def test_batch_read_only_tools_always_allowed():
    """Tools with no path argument are treated as read-only and always parallelised."""
    from mcp.types import Tool

    tool = Tool(
        name="search",
        description="",
        inputSchema={"type": "object", "properties": {}},
    )
    handler = _ok_handler({"hits": []})
    result = await execute_batch(
        invocations=[
            {"tool": "search", "arguments": {}},
            {"tool": "search", "arguments": {}},
        ],
        handlers={"search": handler},
        tools_by_name={"search": tool},
    )
    assert result["status"] == "ok"
    assert len(result["results"]) == 2

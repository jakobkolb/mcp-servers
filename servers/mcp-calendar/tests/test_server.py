"""Tests for server.py — specifically that call_tool offloads blocking I/O."""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock

from mcp.types import TextContent
from mcp_calendar import server


def _make_handler(name: str = "test_tool", result: list = []) -> MagicMock:  # noqa: B006
    handler = MagicMock()
    handler.name = name
    handler.run_tool.return_value = result
    return handler


# ---------------------------------------------------------------------------
# call_tool dispatches to the correct handler
# ---------------------------------------------------------------------------


async def test_call_tool_returns_handler_result() -> None:
    handler = _make_handler(result=[TextContent(type="text", text="hello")])
    handlers = {"test_tool": handler}

    import unittest.mock as mock

    with mock.patch.object(server, "_handlers", handlers):
        result = await server.call_tool("test_tool", {})

    assert result[0].text == "hello"  # type: ignore[union-attr]
    handler.run_tool.assert_called_once_with({})


# ---------------------------------------------------------------------------
# call_tool must not block the event loop
# ---------------------------------------------------------------------------


async def test_call_tool_runs_run_tool_off_event_loop_thread() -> None:
    """run_tool must execute in a worker thread, not on the event-loop thread."""
    loop_thread = threading.current_thread()
    run_tool_thread: list[threading.Thread] = []

    def recording_run_tool(args: dict) -> list:  # type: ignore[type-arg]
        run_tool_thread.append(threading.current_thread())
        return []

    handler = _make_handler()
    handler.run_tool.side_effect = recording_run_tool

    import unittest.mock as mock

    with mock.patch.object(server, "_handlers", {"test_tool": handler}):
        await server.call_tool("test_tool", {})

    assert run_tool_thread, "run_tool was never called"
    assert run_tool_thread[0] is not loop_thread, (
        "run_tool ran on the event-loop thread — it blocks concurrent requests"
    )


async def test_call_tool_does_not_block_event_loop() -> None:
    """Concurrent asyncio tasks must make progress while run_tool is executing."""
    results: list[str] = []

    async def concurrent_task() -> None:
        await asyncio.sleep(0)  # yield to event loop once
        results.append("concurrent")

    def slow_run_tool(args: dict) -> list:  # type: ignore[type-arg]
        time.sleep(0.05)  # simulate blocking network I/O
        results.append("tool")
        return []

    handler = _make_handler()
    handler.run_tool.side_effect = slow_run_tool

    import unittest.mock as mock

    with mock.patch.object(server, "_handlers", {"slow_tool": handler}):
        task = asyncio.create_task(concurrent_task())
        await server.call_tool("slow_tool", {})
        await task

    assert results == ["concurrent", "tool"], (
        f"Event loop was blocked: expected ['concurrent', 'tool'], got {results}"
    )


# ---------------------------------------------------------------------------
# call_tool error handling still works after the fix
# ---------------------------------------------------------------------------


async def test_call_tool_propagates_exception_as_runtime_error() -> None:
    """Exceptions from run_tool must be wrapped in RuntimeError."""
    import pytest

    handler = _make_handler()
    handler.run_tool.side_effect = ValueError("something went wrong")

    import unittest.mock as mock

    with mock.patch.object(server, "_handlers", {"bad_tool": handler}):
        with pytest.raises(RuntimeError, match="something went wrong"):
            await server.call_tool("bad_tool", {})


async def test_call_tool_unknown_tool_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="Unknown tool"):
        await server.call_tool("no_such_tool", {})

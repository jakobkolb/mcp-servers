import pytest
from example_server.server import call_tool, list_resources, list_tools


@pytest.mark.asyncio
async def test_list_tools_returns_hello() -> None:
    tools = await list_tools()
    assert len(tools) == 1
    assert tools[0].name == "hello"


@pytest.mark.asyncio
async def test_hello_tool() -> None:
    result = await call_tool("hello", {"name": "Claude"})
    assert result[0].text == "Hello, Claude!"


@pytest.mark.asyncio
async def test_hello_tool_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await call_tool("nonexistent", {})


@pytest.mark.asyncio
async def test_list_resources_empty() -> None:
    resources = await list_resources()
    assert resources == []

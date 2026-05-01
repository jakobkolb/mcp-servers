import pytest
from example_server.server import list_resources, list_tools


@pytest.mark.asyncio
async def test_list_tools_empty() -> None:
    tools = await list_tools()
    assert tools == []


@pytest.mark.asyncio
async def test_list_resources_empty() -> None:
    resources = await list_resources()
    assert resources == []

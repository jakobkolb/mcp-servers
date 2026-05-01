import logging
import os
from collections.abc import Sequence
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import EmbeddedResource, ImageContent, TextContent

load_dotenv()

from . import tools  # noqa: E402 — after load_dotenv so env vars are present

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-obsidian")

if not os.getenv("OBSIDIAN_API_KEY"):
    raise ValueError(
        f"OBSIDIAN_API_KEY environment variable required. Working directory: {os.getcwd()}"
    )

app = Server("mcp-obsidian")

_handlers = {h.name: h for h in tools.ALL_HANDLERS}


@app.list_tools()
async def list_tools() -> list[tools.Tool]:
    return [h.get_tool_description() for h in _handlers.values()]


@app.call_tool()
async def call_tool(
    name: str, arguments: Any
) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    if not isinstance(arguments, dict):
        raise RuntimeError("arguments must be a dictionary")
    handler = _handlers.get(name)
    if not handler:
        raise ValueError(f"Unknown tool: {name}")
    try:
        return handler.run_tool(arguments)
    except Exception as e:
        logger.error(str(e))
        raise RuntimeError(f"Error: {str(e)}") from e


async def main() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

import logging
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

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
async def list_tools() -> list[Tool]:
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


_session_manager = StreamableHTTPSessionManager(
    app=app,
    event_store=None,
    json_response=False,
    stateless=True,
)


async def _health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@asynccontextmanager
async def _lifespan(_: Starlette) -> AsyncIterator[None]:
    async with _session_manager.run():
        yield


http_app = Starlette(
    routes=[
        Route("/health", _health),
        Mount("/mcp", app=_session_manager.handle_request),
    ],
    lifespan=_lifespan,
)


def main() -> None:
    uvicorn.run(http_app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

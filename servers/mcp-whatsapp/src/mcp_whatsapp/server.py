"""HTTP entrypoint: Streamable-HTTP MCP endpoint and health probe."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .bridge import BridgeClient
from .config import Config, load_config
from .tools import WhatsAppTools
from .whatsapp import Store

logger = logging.getLogger("mcp-whatsapp")


def build_app(config: Config, http: httpx.Client | None = None) -> Starlette:
    if not config.allowed_chats:
        logger.warning("WHATSAPP_ALLOWED_CHATS is empty: no chat content will be served")
    http = http or httpx.Client(base_url=config.bridge_url, timeout=5)
    tools = WhatsAppTools(Store(config), BridgeClient(http))

    async def on_list_tools(
        ctx: ServerRequestContext[Any, Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=tools.list_tools())

    async def on_call_tool(
        ctx: ServerRequestContext[Any, Any], params: CallToolRequestParams
    ) -> CallToolResult:
        try:
            content = await asyncio.to_thread(tools.call, params.name, params.arguments or {})
            return CallToolResult(content=list(content))
        except Exception as e:
            logger.warning("tool %s failed: %s", params.name, e)
            return CallToolResult(is_error=True, content=[TextContent(type="text", text=str(e))])

    server: Server[Any] = Server(
        "mcp-whatsapp", on_list_tools=on_list_tools, on_call_tool=on_call_tool
    )
    sessions = StreamableHTTPSessionManager(
        app=server, event_store=None, json_response=False, stateless=True
    )

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with sessions.run():
            yield

    return Starlette(
        routes=[Route("/health", health), Mount("/mcp", app=sessions.handle_request)],
        lifespan=lifespan,
    )


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    uvicorn.run(build_app(load_config()), host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import mcp.types as types
import uvicorn
from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route


async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="hello",
            description="Returns a greeting for the given name.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name to greet"},
                },
                "required": ["name"],
            },
        )
    ]


async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "hello":
        who = arguments.get("name", "world")
        return [types.TextContent(type="text", text=f"Hello, {who}!")]
    raise ValueError(f"Unknown tool: {name}")


async def list_resources() -> list[types.Resource]:
    return []


async def _on_list_tools(
    ctx: ServerRequestContext[Any, Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=await list_tools())


async def _on_call_tool(
    ctx: ServerRequestContext[Any, Any], params: types.CallToolRequestParams
) -> types.CallToolResult:
    try:
        content = await call_tool(params.name, params.arguments or {})
        return types.CallToolResult(content=list(content))
    except Exception as e:
        return types.CallToolResult(
            is_error=True, content=[types.TextContent(type="text", text=str(e))]
        )


async def _on_list_resources(
    ctx: ServerRequestContext[Any, Any], params: types.PaginatedRequestParams | None
) -> types.ListResourcesResult:
    return types.ListResourcesResult(resources=await list_resources())


server: Server[Any] = Server(
    "example-server",
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
    on_list_resources=_on_list_resources,
)


_session_manager = StreamableHTTPSessionManager(
    app=server,
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

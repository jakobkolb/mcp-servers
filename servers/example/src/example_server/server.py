import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Resource, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

app = Server("example-server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return []


@app.list_resources()
async def list_resources() -> list[Resource]:
    return []


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


if __name__ == "__main__":
    main()

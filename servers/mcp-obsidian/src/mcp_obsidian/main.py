from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import Server

from mcp_obsidian.config import Config
from mcp_obsidian.tools.registry import register_all_tools


def build_server(config: Config) -> Server:
    server = Server("mcp-obsidian")
    register_all_tools(server, config)
    return server


async def run_stdio(server: Server) -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def run_streamable_http(server: Server, config: Config) -> None:
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", endpoint=health),
            Mount("/mcp", app=session_manager.handle_request),
        ],
        lifespan=lifespan,
    )
    uvicorn_config = uvicorn.Config(
        app,
        host=config.mcp_host,
        port=config.mcp_port,
        log_level=config.log_level.lower(),
    )
    await uvicorn.Server(uvicorn_config).serve()


async def amain() -> None:
    config = Config()  # type: ignore[call-arg]
    logging.basicConfig(level=config.log_level.upper())
    server = build_server(config)
    transport = config.mcp_transport.lower().replace("_", "-")

    if transport == "stdio":
        await run_stdio(server)
    elif transport in {"streamable-http", "http", "sse"}:
        if transport == "sse":
            logging.warning("MCP_TRANSPORT=sse is deprecated; serving Streamable HTTP on /mcp")
        await run_streamable_http(server, config)
    else:
        raise ValueError(f"Unsupported MCP_TRANSPORT: {config.mcp_transport}")


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()

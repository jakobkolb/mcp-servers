from __future__ import annotations

import asyncio
import logging

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


async def run_sse(server: Server, config: Config) -> None:
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Mount, Route

    sse_transport = SseServerTransport("/messages")

    async def handle_sse(request: Request) -> None:
        async with sse_transport.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages", app=sse_transport.handle_post_message),
        ]
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

    if config.mcp_transport.lower() == "stdio":
        await run_stdio(server)
    else:
        await run_sse(server, config)


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()

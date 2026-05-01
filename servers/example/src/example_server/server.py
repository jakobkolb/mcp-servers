import asyncio

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

server: Server = Server("example-server")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return []


@server.list_resources()
async def list_resources() -> list[types.Resource]:
    return []


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())

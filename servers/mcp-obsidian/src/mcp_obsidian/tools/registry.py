from mcp.server import Server

from mcp_obsidian.config import Config
from mcp_obsidian.tools.reading import register_reading_tools


def register_all_tools(server: Server, config: Config) -> None:
    register_reading_tools(server, config)

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from mcp_obsidian.config import Config
from mcp_obsidian.errors import (
    BatchTooLargeError,
    NotANoteError,
    NoteAlreadyExistsError,
    NoteNotFoundError,
    PatchAmbiguousError,
    PatchNoMatchError,
    TaskStateError,
    VaultError,
    VaultPathError,
)
from mcp_obsidian.tools import (
    batch,
    organizing,
    reading,
    searching,
    task_tools,
    vault_wide,
    writing,
)


def _error_result(code: str, message: str) -> CallToolResult:
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text=f"{code}: {message}")],
    )


def register_all_tools(server: Server, config: Config) -> None:
    tool_modules = [reading, searching, writing, organizing, vault_wide, task_tools]

    all_tools: list[Tool] = []
    all_handlers: dict[str, Any] = {}

    for mod in tool_modules:
        all_tools.extend(mod.get_tools())
        all_handlers.update(mod.get_handlers(config))

    # batch_tool registered last so it can reference all other handlers/tools.
    batch.register(config, all_tools, all_handlers)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return all_tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        handler = all_handlers.get(name)
        if handler is None:
            return _error_result("NOT_IMPLEMENTED", f"Tool {name!r} is not implemented.")

        try:
            result = await handler(arguments or {})
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(result, ensure_ascii=False, default=str),
                    )
                ]
            )
        except NoteAlreadyExistsError as e:
            return _error_result("ALREADY_EXISTS", str(e))
        except NoteNotFoundError as e:
            return _error_result("NOT_FOUND", str(e))
        except NotANoteError as e:
            return _error_result("NOT_A_NOTE", str(e))
        except VaultPathError as e:
            return _error_result("INVALID_PATH", str(e))
        except PatchNoMatchError as e:
            return _error_result("PATCH_NO_MATCH", str(e))
        except PatchAmbiguousError as e:
            return _error_result("PATCH_AMBIGUOUS", str(e))
        except BatchTooLargeError as e:
            return _error_result("BATCH_TOO_LARGE", str(e))
        except TaskStateError as e:
            return _error_result("TASK_STATE_ERROR", str(e))
        except VaultError as e:
            return _error_result("VAULT_ERROR", str(e))
        except Exception as e:
            return _error_result("INTERNAL_ERROR", str(e))

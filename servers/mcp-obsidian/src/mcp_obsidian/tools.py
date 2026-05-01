import json
import os
from collections.abc import Sequence
from typing import Any

from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

from . import obsidian as obsidian_module

_api_key = os.getenv("OBSIDIAN_API_KEY", "")
_obsidian_host = os.getenv("OBSIDIAN_HOST", "127.0.0.1")

if not _api_key:
    raise ValueError(
        f"OBSIDIAN_API_KEY environment variable required. Working directory: {os.getcwd()}"
    )


def _api() -> obsidian_module.Obsidian:
    return obsidian_module.Obsidian(api_key=_api_key, host=_obsidian_host)


ToolResult = Sequence[TextContent | ImageContent | EmbeddedResource]


class ToolHandler:
    def __init__(self, tool_name: str) -> None:
        self.name = tool_name

    def get_tool_description(self) -> Tool:
        raise NotImplementedError

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class ListFilesInVaultToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_list_files_in_vault")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=(
                "Lists all files and directories in the root directory of your Obsidian vault."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        files = _api().list_files_in_vault()
        return [TextContent(type="text", text=json.dumps(files, indent=2))]


class ListFilesInDirToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_list_files_in_dir")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=(
                "Lists all files and directories that exist in a specific Obsidian directory."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dirpath": {
                        "type": "string",
                        "description": (
                            "Path to list files from (relative to your vault root)."
                            " Note that empty directories will not be returned."
                        ),
                    },
                },
                "required": ["dirpath"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "dirpath" not in args:
            raise RuntimeError("dirpath argument missing in arguments")
        files = _api().list_files_in_dir(args["dirpath"])
        return [TextContent(type="text", text=json.dumps(files, indent=2))]


class GetFileContentsToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_get_file_contents")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Return the content of a single file in your vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the relevant file (relative to your vault root).",
                        "format": "path",
                    },
                },
                "required": ["filepath"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "filepath" not in args:
            raise RuntimeError("filepath argument missing in arguments")
        content = _api().get_file_contents(args["filepath"])
        return [TextContent(type="text", text=json.dumps(content, indent=2))]


class BatchGetFileContentsToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_batch_get_file_contents")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=(
                "Return the contents of multiple files in your vault, concatenated with headers."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filepaths": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "Path to a file (relative to your vault root).",
                            "format": "path",
                        },
                        "description": "List of file paths to read.",
                    },
                },
                "required": ["filepaths"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "filepaths" not in args:
            raise RuntimeError("filepaths argument missing in arguments")
        content = _api().get_batch_file_contents(args["filepaths"])
        return [TextContent(type="text", text=content)]


class SearchToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_simple_search")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=(
                "Simple search for documents matching a specified text query"
                " across all files in the vault.\n\n"
                "Use this tool when you want to do a simple text search."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for in the vault.",
                    },
                    "context_length": {
                        "type": "integer",
                        "description": (
                            "How much context to return around the matching string (default: 100)."
                        ),
                        "default": 100,
                    },
                },
                "required": ["query"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "query" not in args:
            raise RuntimeError("query argument missing in arguments")
        context_length = args.get("context_length", 100)
        results = _api().search(args["query"], context_length)
        formatted = [
            {
                "filename": r.get("filename", ""),
                "score": r.get("score", 0),
                "matches": [
                    {
                        "context": m.get("context", ""),
                        "match_position": {
                            "start": m.get("match", {}).get("start", 0),
                            "end": m.get("match", {}).get("end", 0),
                        },
                    }
                    for m in r.get("matches", [])
                ],
            }
            for r in results
        ]
        return [TextContent(type="text", text=json.dumps(formatted, indent=2))]


class ComplexSearchToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_complex_search")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=(
                "Complex search for documents using a JsonLogic query.\n\n"
                "Supports standard JsonLogic operators plus 'glob' and 'regexp'"
                " for pattern matching. Results must be non-falsy.\n\n"
                "Use this tool when you want to do a complex search,"
                " e.g. for all documents with certain tags.\n\n"
                "ALWAYS follow query syntax in examples.\n\n"
                "Examples\n\n"
                '1. Match all markdown files\n{"glob": ["*.md", {"var": "path"}]}\n\n'
                "2. Match all markdown files with 1221 substring\n"
                '{"and": [{"glob": ["*.md", {"var": "path"}]},'
                ' {"regexp": [".*1221.*", {"var": "content"}]}]}\n\n'
                "3. Match markdown files in Work folder containing name Keaton\n"
                '{"and": [{"glob": ["*.md", {"var": "path"}]},'
                ' {"regexp": [".*Work.*", {"var": "path"}]},'
                ' {"regexp": ["Keaton", {"var": "content"}]}]}'
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "object",
                        "description": (
                            'JsonLogic query object. Example: {"glob": ["*.md", {"var": "path"}]}'
                            " matches all markdown files."
                        ),
                    }
                },
                "required": ["query"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "query" not in args:
            raise RuntimeError("query argument missing in arguments")
        results = _api().search_json(args["query"])
        return [TextContent(type="text", text=json.dumps(results, indent=2))]


class AppendContentToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_append_content")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Append content to a new or existing file in the vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the file (relative to vault root).",
                        "format": "path",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to append to the file.",
                    },
                },
                "required": ["filepath", "content"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "filepath" not in args or "content" not in args:
            raise RuntimeError("filepath and content arguments required")
        _api().append_content(args["filepath"], args["content"])
        msg = f"Successfully appended content to {args['filepath']}"
        return [TextContent(type="text", text=msg)]


class PatchContentToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_patch_content")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=(
                "Insert content into an existing note relative to a heading,"
                " block reference, or frontmatter field."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the file (relative to vault root).",
                        "format": "path",
                    },
                    "operation": {
                        "type": "string",
                        "description": "Operation to perform.",
                        "enum": ["append", "prepend", "replace"],
                    },
                    "target_type": {
                        "type": "string",
                        "description": "Type of target to patch.",
                        "enum": ["heading", "block", "frontmatter"],
                    },
                    "target": {
                        "type": "string",
                        "description": (
                            "Target identifier: heading path,"
                            " block reference, or frontmatter field."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to insert.",
                    },
                },
                "required": ["filepath", "operation", "target_type", "target", "content"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        required = ["filepath", "operation", "target_type", "target", "content"]
        if not all(k in args for k in required):
            raise RuntimeError(
                "filepath, operation, target_type, target and content arguments required"
            )
        _api().patch_content(
            args["filepath"],
            args["operation"],
            args["target_type"],
            args["target"],
            args["content"],
        )
        msg = f"Successfully patched content in {args['filepath']}"
        return [TextContent(type="text", text=msg)]


class PutContentToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_put_content")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=(
                "Create a new file in your vault or replace the content of an existing one."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the relevant file (relative to your vault root).",
                        "format": "path",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file.",
                    },
                },
                "required": ["filepath", "content"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "filepath" not in args or "content" not in args:
            raise RuntimeError("filepath and content arguments required")
        _api().put_content(args["filepath"], args["content"])
        return [TextContent(type="text", text=f"Successfully wrote content to {args['filepath']}")]


class DeleteFileToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_delete_file")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Delete a file or directory from the vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": (
                            "Path to the file or directory to delete (relative to vault root)."
                        ),
                        "format": "path",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Confirmation to delete the file (must be true).",
                        "default": False,
                    },
                },
                "required": ["filepath", "confirm"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "filepath" not in args:
            raise RuntimeError("filepath argument missing in arguments")
        if not args.get("confirm", False):
            raise RuntimeError("confirm must be set to true to delete a file")
        _api().delete_file(args["filepath"])
        return [TextContent(type="text", text=f"Successfully deleted {args['filepath']}")]


class PeriodicNotesToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_get_periodic_note")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Get current periodic note for the specified period.",
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "The period type.",
                        "enum": ["daily", "weekly", "monthly", "quarterly", "yearly"],
                    },
                    "type": {
                        "type": "string",
                        "description": (
                            "Type of data to get: 'content' returns Markdown;"
                            " 'metadata' includes frontmatter, tags, paths, and content."
                        ),
                        "default": "content",
                        "enum": ["content", "metadata"],
                    },
                },
                "required": ["period"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "period" not in args:
            raise RuntimeError("period argument missing in arguments")
        period = args["period"]
        valid_periods = ["daily", "weekly", "monthly", "quarterly", "yearly"]
        if period not in valid_periods:
            valid = ", ".join(valid_periods)
            raise RuntimeError(f"Invalid period: {period}. Must be one of: {valid}")
        note_type = args.get("type", "content")
        if note_type not in ("content", "metadata"):
            raise RuntimeError(f"Invalid type: {note_type}. Must be 'content' or 'metadata'")
        content = _api().get_periodic_note(period, note_type)
        return [TextContent(type="text", text=content)]


class RecentPeriodicNotesToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_get_recent_periodic_notes")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Get most recent periodic notes for the specified period type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "The period type.",
                        "enum": ["daily", "weekly", "monthly", "quarterly", "yearly"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of notes to return (default: 5).",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 50,
                    },
                    "include_content": {
                        "type": "boolean",
                        "description": "Whether to include note content (default: false).",
                        "default": False,
                    },
                },
                "required": ["period"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        if "period" not in args:
            raise RuntimeError("period argument missing in arguments")
        period = args["period"]
        valid_periods = ["daily", "weekly", "monthly", "quarterly", "yearly"]
        if period not in valid_periods:
            valid = ", ".join(valid_periods)
            raise RuntimeError(f"Invalid period: {period}. Must be one of: {valid}")
        limit = args.get("limit", 5)
        if not isinstance(limit, int) or limit < 1:
            raise RuntimeError(f"Invalid limit: {limit}. Must be a positive integer")
        include_content = args.get("include_content", False)
        if not isinstance(include_content, bool):
            raise RuntimeError(f"Invalid include_content: {include_content}. Must be a boolean")
        results = _api().get_recent_periodic_notes(period, limit, include_content)
        return [TextContent(type="text", text=json.dumps(results, indent=2))]


class RecentChangesToolHandler(ToolHandler):
    def __init__(self) -> None:
        super().__init__("obsidian_get_recent_changes")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="Get recently modified files in the vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of files to return (default: 10).",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "days": {
                        "type": "integer",
                        "description": (
                            "Only include files modified within this many days (default: 90)."
                        ),
                        "minimum": 1,
                        "default": 90,
                    },
                },
            },
        )

    def run_tool(self, args: dict[str, Any]) -> ToolResult:
        limit = args.get("limit", 10)
        if not isinstance(limit, int) or limit < 1:
            raise RuntimeError(f"Invalid limit: {limit}. Must be a positive integer")
        days = args.get("days", 90)
        if not isinstance(days, int) or days < 1:
            raise RuntimeError(f"Invalid days: {days}. Must be a positive integer")
        results = _api().get_recent_changes(limit, days)
        return [TextContent(type="text", text=json.dumps(results, indent=2))]


ALL_HANDLERS: list[ToolHandler] = [
    ListFilesInVaultToolHandler(),
    ListFilesInDirToolHandler(),
    GetFileContentsToolHandler(),
    BatchGetFileContentsToolHandler(),
    SearchToolHandler(),
    ComplexSearchToolHandler(),
    AppendContentToolHandler(),
    PatchContentToolHandler(),
    PutContentToolHandler(),
    DeleteFileToolHandler(),
    PeriodicNotesToolHandler(),
    RecentPeriodicNotesToolHandler(),
    RecentChangesToolHandler(),
]

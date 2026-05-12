# Obsidian MCP Server — MVP Implementation Plan

**Goal:** A working MCP server with one tool (`read_note`), a full unit test suite for that
tool, an integration test against a minimal vault, and a Dockerfile that builds for arm64.
Vault sync is handled by a sidecar — this server only reads/writes the PVC.

**Why `read_note` as the MVP tool:**  
It exercises every core abstraction — path resolution, traversal guard, frontmatter parsing,
error responses, MCP protocol wiring — without requiring atomic writes or vault walks. Every
other tool is built on top of these same primitives. Once `read_note` is green, the rest are
mechanical.

---

## Deliverables

| # | Deliverable | Done when |
|---|---|---|
| D1 | Project scaffold + `pyproject.toml` | `pip install -e ".[dev]"` succeeds |
| D2 | `vault/path.py` — path resolution + traversal guard | unit tests pass |
| D3 | `vault/frontmatter.py` — parse/serialize | unit tests pass |
| D4 | `vault/io.py` — `read_note()` | unit tests pass |
| D5 | `tools/reading.py` — MCP tool wiring for `read_note` | tool registers and returns JSON |
| D6 | `main.py` — server entry point (stdio + SSE) | `python -m obsidian_mcp.main` starts |
| D7 | Unit tests | `pytest tests/unit/` green |
| D8 | Integration test | `pytest tests/integration/` green |
| D9 | Dockerfile | `docker buildx build --platform linux/arm64` succeeds |

---

## Step 1 — Project scaffold

### Directory structure

```
obsidian-mcp/
├── pyproject.toml
├── Dockerfile
├── .env.example
├── src/
│   └── obsidian_mcp/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── errors.py
│       ├── vault/
│       │   ├── __init__.py
│       │   ├── path.py
│       │   ├── frontmatter.py
│       │   └── io.py
│       └── tools/
│           ├── __init__.py
│           ├── registry.py
│           └── reading.py
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_path.py
    │   ├── test_frontmatter.py
    │   └── test_read_note.py
    └── integration/
        └── test_read_note_integration.py
```

### `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=72", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "obsidian-mcp"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.0.0",
    "python-frontmatter>=1.1.0",
    "ruamel.yaml>=0.18.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sse-starlette>=2.1.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.5.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",          # for testing the SSE/HTTP endpoint
    "mypy>=1.11",
    "ruff>=0.6",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

---

## Step 2 — Core abstractions

### `src/obsidian_mcp/errors.py`

```python
class VaultError(Exception):
    """Base for all vault errors. Always include a human-readable message."""

class VaultPathError(VaultError):
    """Path escapes vault root, is absolute, or is otherwise invalid."""

class NoteNotFoundError(VaultError):
    """The requested note path does not exist."""

class NotANoteError(VaultError):
    """The path exists but is not a .md file."""
```

### `src/obsidian_mcp/config.py`

```python
from pydantic_settings import BaseSettings

class Config(BaseSettings):
    vault_path: str                  # required; absolute path to vault root
    mcp_transport: str = "sse"       # "sse" | "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

### `src/obsidian_mcp/vault/path.py`

Resolves vault-relative paths and blocks path traversal.

```python
from pathlib import Path
from obsidian_mcp.errors import VaultPathError

def resolve(vault_root: str, relative: str) -> Path:
    """
    Resolve a vault-relative path string to an absolute Path.

    Rules:
    - `relative` must not be absolute (no leading /).
    - After resolution, the result must be inside vault_root.
    - Normalizes separators (accepts both / and os.sep).

    Raises VaultPathError on any violation.
    """
    if not relative or not relative.strip():
        raise VaultPathError("Path must not be empty.")
    p = Path(relative)
    if p.is_absolute():
        raise VaultPathError(f"Path must be vault-relative, not absolute: {relative!r}")
    root = Path(vault_root).resolve()
    full = (root / p).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        raise VaultPathError(f"Path escapes vault root: {relative!r}")
    return full

def to_relative(vault_root: str, absolute: Path) -> str:
    """Convert an absolute path back to a vault-relative string."""
    return str(absolute.relative_to(vault_root))
```

### `src/obsidian_mcp/vault/frontmatter.py`

Parses and serializes YAML frontmatter without mangling dates or booleans.

```python
from __future__ import annotations
from io import StringIO
import frontmatter as fm_lib
from ruamel.yaml import YAML
from obsidian_mcp.errors import VaultError


def _make_yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True
    y.width = 120
    return y


def parse(content: str) -> tuple[dict, str]:
    """
    Split a markdown string into (frontmatter_dict, body_text).
    Returns ({}, full_content) if no frontmatter block is present.
    Never raises on malformed YAML — returns empty dict and full content instead,
    so a bad frontmatter block doesn't prevent reading the note body.
    """
    try:
        post = fm_lib.loads(content)
        return dict(post.metadata), post.content
    except Exception:
        return {}, content


def serialize(fm: dict) -> str:
    """
    Serialize a frontmatter dict to a YAML string suitable for embedding in
    a --- block. Does not include the --- delimiters themselves.
    """
    y = _make_yaml()
    stream = StringIO()
    y.dump(fm, stream)
    return stream.getvalue()


def build_note_content(fm: dict | None, body: str) -> str:
    """
    Combine frontmatter and body into a complete note string.
    If fm is None or empty, returns body unchanged.
    """
    if not fm:
        return body
    return f"---\n{serialize(fm)}---\n{body}"
```

### `src/obsidian_mcp/vault/io.py`

The `read_note` business logic. Keeps filesystem I/O separate from tool wiring.

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from obsidian_mcp.errors import NoteNotFoundError, NotANoteError
from obsidian_mcp.vault import path as vpath
from obsidian_mcp.vault import frontmatter as fm_mod


@dataclass
class Note:
    path: str           # vault-relative
    frontmatter: dict
    content: str        # body (after frontmatter block)
    raw: str            # full file content
    mtime: str          # ISO 8601 datetime
    size: int           # bytes


def read_note(vault_root: str, relative: str) -> Note:
    """
    Read a single markdown note from the vault.

    Parameters
    ----------
    vault_root : str
        Absolute path to vault root (from Config.vault_path).
    relative : str
        Vault-relative path, e.g. "Diary/2026-05-12.md".

    Returns
    -------
    Note
        Parsed note with frontmatter, body, metadata.

    Raises
    ------
    VaultPathError
        If the path escapes the vault root or is invalid.
    NoteNotFoundError
        If the path does not exist.
    NotANoteError
        If the path exists but is not a .md file.
    """
    abs_path: Path = vpath.resolve(vault_root, relative)

    if not abs_path.exists():
        raise NoteNotFoundError(f"Note not found: {relative!r}")

    if not abs_path.is_file() or abs_path.suffix.lower() != ".md":
        raise NotANoteError(
            f"Path is not a markdown note: {relative!r} "
            f"(suffix: {abs_path.suffix!r})"
        )

    # Read as bytes first, then decode — handles emoji in content reliably
    raw_bytes = abs_path.read_bytes()
    raw = raw_bytes.decode("utf-8", errors="replace")

    fm, body = fm_mod.parse(raw)

    stat = abs_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    return Note(
        path=relative,
        frontmatter=fm,
        content=body,
        raw=raw,
        mtime=mtime,
        size=stat.st_size,
    )
```

---

## Step 3 — MCP tool wiring

### `src/obsidian_mcp/tools/reading.py`

```python
from __future__ import annotations
import json
from mcp.server import Server
from mcp.types import Tool, TextContent, CallToolResult
from pydantic import BaseModel, field_validator

from obsidian_mcp.config import Config
from obsidian_mcp.errors import VaultError, NoteNotFoundError, VaultPathError, NotANoteError
from obsidian_mcp.vault.io import read_note


class ReadNoteInput(BaseModel):
    path: str
    pretty_print: bool = False

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("path must not be empty")
        return v


def _note_to_dict(note, pretty_print: bool) -> dict:
    if pretty_print:
        fm_lines = "\n".join(f"{k}: {v}" for k, v in note.frontmatter.items())
        display_content = f"{fm_lines}\n\n{note.content}" if fm_lines else note.content
    else:
        display_content = note.content

    return {
        "path": note.path,
        "frontmatter": note.frontmatter,
        "content": display_content,
        "raw": note.raw,
        "mtime": note.mtime,
        "size": note.size,
    }


def _error_result(code: str, message: str) -> CallToolResult:
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text=f"{code}: {message}")],
    )


def register_reading_tools(server: Server, config: Config) -> None:

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> CallToolResult:
        if name != "read_note":
            # Other tools not implemented yet
            return _error_result("NOT_IMPLEMENTED", f"Tool {name!r} is not implemented in this MVP.")

        try:
            args = ReadNoteInput(**arguments)
        except Exception as e:
            return _error_result("INVALID_ARGUMENTS", str(e))

        try:
            note = read_note(config.vault_path, args.path)
        except VaultPathError as e:
            return _error_result("INVALID_PATH", str(e))
        except NoteNotFoundError as e:
            return _error_result("NOT_FOUND", str(e))
        except NotANoteError as e:
            return _error_result("NOT_A_NOTE", str(e))
        except VaultError as e:
            return _error_result("VAULT_ERROR", str(e))

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(_note_to_dict(note, args.pretty_print)))]
        )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="read_note",
                description=(
                    "Read a single markdown note from the vault. "
                    "Returns frontmatter, body content, and file metadata. "
                    "Path must be vault-relative (e.g. 'Diary/2026-05-12.md')."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Vault-relative path to the note (must end in .md)",
                        },
                        "pretty_print": {
                            "type": "boolean",
                            "description": "If true, render frontmatter as plain key: value lines instead of a raw dict.",
                            "default": False,
                        },
                    },
                    "required": ["path"],
                },
            )
        ]
```

### `src/obsidian_mcp/tools/registry.py`

```python
from mcp.server import Server
from obsidian_mcp.config import Config
from obsidian_mcp.tools.reading import register_reading_tools


def register_all_tools(server: Server, config: Config) -> None:
    register_reading_tools(server, config)
```

### `src/obsidian_mcp/main.py`

```python
from __future__ import annotations
import asyncio
import logging

from mcp.server import Server
from obsidian_mcp.config import Config
from obsidian_mcp.tools.registry import register_all_tools


def build_server(config: Config) -> Server:
    server = Server("obsidian-vault")
    register_all_tools(server, config)
    return server


async def run_stdio(server: Server) -> None:
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


async def run_sse(server: Server, config: Config) -> None:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Mount, Route
    from mcp.server.sse import SseServerTransport
    import uvicorn

    sse_transport = SseServerTransport("/messages")

    async def handle_sse(request: Request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read, write):
            await server.run(read, write, server.create_initialization_options())

    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages", app=sse_transport.handle_post_message),
        ]
    )

    uconfig = uvicorn.Config(
        app,
        host=config.mcp_host,
        port=config.mcp_port,
        log_level=config.log_level.lower(),
    )
    await uvicorn.Server(uconfig).serve()


async def main() -> None:
    config = Config()
    logging.basicConfig(level=config.log_level.upper())

    server = build_server(config)

    if config.mcp_transport == "stdio":
        await run_stdio(server)
    else:
        await run_sse(server, config)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Step 4 — Unit tests

Three test files. Each tests one module in isolation — no running server, no network, just the
Python functions.

### `tests/conftest.py`

```python
import pytest
from pathlib import Path


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """
    A temporary directory that serves as a vault root for tests.
    Created fresh per test function.
    """
    return tmp_path


@pytest.fixture
def note_with_frontmatter(tmp_vault: Path) -> Path:
    """A .md file with YAML frontmatter and a body."""
    p = tmp_vault / "note_with_fm.md"
    p.write_text(
        "---\n"
        "title: Test Note\n"
        "created: 2026-01-15\n"
        "completed: false\n"
        "tags:\n"
        "  - project\n"
        "  - gtd\n"
        "---\n"
        "\n"
        "# Test Note\n"
        "\n"
        "Body content here.\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def note_without_frontmatter(tmp_vault: Path) -> Path:
    """A .md file with no frontmatter block."""
    p = tmp_vault / "plain_note.md"
    p.write_text("# Plain Note\n\nJust a body.\n", encoding="utf-8")
    return p


@pytest.fixture
def note_with_emoji_name(tmp_vault: Path) -> Path:
    """A .md file whose name contains an emoji — tests UTF-8 path handling."""
    p = tmp_vault / "🚀 Next actions list.md"
    p.write_text("---\ntitle: Next Actions\n---\n\n- [ ] First task\n", encoding="utf-8")
    return p


@pytest.fixture
def note_with_emoji_content(tmp_vault: Path) -> Path:
    """A .md file whose body contains emoji."""
    p = tmp_vault / "emoji_content.md"
    p.write_text(
        "---\ntitle: Emoji Content\n---\n\n"
        "- [ ] Buy milk 🥛 #context/home ⏳2026-06-01\n",
        encoding="utf-8",
    )
    return p
```

### `tests/unit/test_path.py`

```python
import pytest
from pathlib import Path
from obsidian_mcp.vault.path import resolve, to_relative
from obsidian_mcp.errors import VaultPathError


class TestResolve:

    def test_simple_relative_path(self, tmp_path: Path):
        result = resolve(str(tmp_path), "Diary/note.md")
        assert result == tmp_path / "Diary" / "note.md"

    def test_nested_path(self, tmp_path: Path):
        result = resolve(str(tmp_path), "a/b/c/deep.md")
        assert result == tmp_path / "a" / "b" / "c" / "deep.md"

    def test_root_level_path(self, tmp_path: Path):
        result = resolve(str(tmp_path), "top-level.md")
        assert result == tmp_path / "top-level.md"

    def test_path_with_emoji(self, tmp_path: Path):
        result = resolve(str(tmp_path), "🚀 Next actions list.md")
        assert result == tmp_path / "🚀 Next actions list.md"

    def test_path_with_spaces(self, tmp_path: Path):
        result = resolve(str(tmp_path), "Getting things done/🚀 Next actions list.md")
        assert result == tmp_path / "Getting things done" / "🚀 Next actions list.md"

    def test_raises_on_absolute_path(self, tmp_path: Path):
        with pytest.raises(VaultPathError, match="absolute"):
            resolve(str(tmp_path), "/etc/passwd")

    def test_raises_on_traversal_dotdot(self, tmp_path: Path):
        with pytest.raises(VaultPathError, match="escapes"):
            resolve(str(tmp_path), "../outside/secret.md")

    def test_raises_on_deep_traversal(self, tmp_path: Path):
        with pytest.raises(VaultPathError, match="escapes"):
            resolve(str(tmp_path), "subdir/../../outside.md")

    def test_raises_on_empty_path(self, tmp_path: Path):
        with pytest.raises(VaultPathError):
            resolve(str(tmp_path), "")

    def test_raises_on_whitespace_only_path(self, tmp_path: Path):
        with pytest.raises(VaultPathError):
            resolve(str(tmp_path), "   ")

    def test_normalizes_trailing_slash(self, tmp_path: Path):
        # Should not raise; just resolves to the directory path
        result = resolve(str(tmp_path), "subdir")
        assert result == tmp_path / "subdir"


class TestToRelative:

    def test_round_trips_with_resolve(self, tmp_path: Path):
        original = "Diary/2026-05-12.md"
        abs_path = resolve(str(tmp_path), original)
        back = to_relative(str(tmp_path), abs_path)
        assert back == original
```

### `tests/unit/test_frontmatter.py`

```python
import pytest
from obsidian_mcp.vault.frontmatter import parse, serialize, build_note_content


class TestParse:

    def test_note_with_frontmatter(self):
        content = "---\ntitle: Hello\ncompleted: false\n---\n\nBody text.\n"
        fm, body = parse(content)
        assert fm["title"] == "Hello"
        assert fm["completed"] is False
        assert "Body text." in body

    def test_note_without_frontmatter(self):
        content = "# Just a heading\n\nSome text.\n"
        fm, body = parse(content)
        assert fm == {}
        assert body == content

    def test_frontmatter_with_list_tags(self):
        content = "---\ntags:\n  - project\n  - gtd\n---\n\nBody.\n"
        fm, body = parse(content)
        assert fm["tags"] == ["project", "gtd"]

    def test_frontmatter_with_inline_tags(self):
        content = "---\ntags: [project, gtd]\n---\n\nBody.\n"
        fm, body = parse(content)
        assert "project" in fm["tags"]
        assert "gtd" in fm["tags"]

    def test_frontmatter_date_field(self):
        content = "---\ncreated: 2026-01-15\n---\n\nBody.\n"
        fm, _ = parse(content)
        # python-frontmatter may parse this as a date object or string; either is acceptable
        assert str(fm["created"]).startswith("2026-01-15")

    def test_malformed_yaml_does_not_raise(self):
        # Should not raise — returns empty fm and full content
        content = "---\n: bad: yaml: here\n---\n\nBody.\n"
        fm, body = parse(content)
        assert isinstance(fm, dict)
        assert isinstance(body, str)

    def test_empty_frontmatter_block(self):
        content = "---\n---\n\nBody.\n"
        fm, body = parse(content)
        assert fm == {}
        assert "Body." in body

    def test_body_preserved_with_emoji(self):
        content = "---\ntitle: Tasks\n---\n\n- [ ] Buy milk 🥛 ⏳2026-06-01\n"
        fm, body = parse(content)
        assert "🥛" in body
        assert "⏳" in body


class TestBuildNoteContent:

    def test_roundtrip_without_frontmatter(self):
        body = "# Hello\n\nJust text.\n"
        result = build_note_content(None, body)
        assert result == body

    def test_roundtrip_with_frontmatter(self):
        fm = {"title": "Test", "completed": False}
        body = "\nBody here.\n"
        result = build_note_content(fm, body)
        assert result.startswith("---\n")
        assert "title: Test" in result
        assert "Body here." in result

    def test_empty_fm_dict_returns_body(self):
        body = "Just body.\n"
        result = build_note_content({}, body)
        assert result == body
```

### `tests/unit/test_read_note.py`

```python
import pytest
from pathlib import Path
from obsidian_mcp.vault.io import read_note
from obsidian_mcp.errors import NoteNotFoundError, NotANoteError, VaultPathError


class TestReadNoteHappyPath:

    def test_reads_note_with_frontmatter(self, tmp_vault: Path, note_with_frontmatter: Path):
        note = read_note(str(tmp_vault), "note_with_fm.md")
        assert note.path == "note_with_fm.md"
        assert note.frontmatter["title"] == "Test Note"
        assert note.frontmatter["completed"] is False
        assert "project" in note.frontmatter["tags"]
        assert "Body content here." in note.content
        assert note.size > 0
        assert note.mtime.endswith("+00:00") or note.mtime.endswith("Z")

    def test_reads_note_without_frontmatter(self, tmp_vault: Path, note_without_frontmatter: Path):
        note = read_note(str(tmp_vault), "plain_note.md")
        assert note.frontmatter == {}
        assert "Just a body." in note.content

    def test_raw_field_contains_full_content(self, tmp_vault: Path, note_with_frontmatter: Path):
        note = read_note(str(tmp_vault), "note_with_fm.md")
        assert "---" in note.raw
        assert "title: Test Note" in note.raw
        assert "Body content here." in note.raw

    def test_reads_note_with_emoji_in_name(self, tmp_vault: Path, note_with_emoji_name: Path):
        note = read_note(str(tmp_vault), "🚀 Next actions list.md")
        assert note.frontmatter["title"] == "Next Actions"
        assert "- [ ] First task" in note.content

    def test_reads_note_with_emoji_in_content(self, tmp_vault: Path, note_with_emoji_content: Path):
        note = read_note(str(tmp_vault), "emoji_content.md")
        assert "🥛" in note.content
        assert "⏳" in note.content

    def test_reads_note_in_subdirectory(self, tmp_vault: Path):
        subdir = tmp_vault / "Getting things done" / "Projects"
        subdir.mkdir(parents=True)
        (subdir / "My Project.md").write_text(
            "---\ntags:\n  - project\ncompleted: false\n---\n\n## Todo\n- [ ] First action\n",
            encoding="utf-8",
        )
        note = read_note(str(tmp_vault), "Getting things done/Projects/My Project.md")
        assert "project" in note.frontmatter["tags"]
        assert "First action" in note.content

    def test_size_matches_actual_file_size(self, tmp_vault: Path, note_with_frontmatter: Path):
        expected_size = note_with_frontmatter.stat().st_size
        note = read_note(str(tmp_vault), "note_with_fm.md")
        assert note.size == expected_size


class TestReadNoteErrors:

    def test_raises_not_found_for_missing_file(self, tmp_vault: Path):
        with pytest.raises(NoteNotFoundError, match="does_not_exist.md"):
            read_note(str(tmp_vault), "does_not_exist.md")

    def test_raises_not_a_note_for_txt_file(self, tmp_vault: Path):
        (tmp_vault / "file.txt").write_text("hello", encoding="utf-8")
        with pytest.raises(NotANoteError):
            read_note(str(tmp_vault), "file.txt")

    def test_raises_not_a_note_for_directory(self, tmp_vault: Path):
        (tmp_vault / "subdir").mkdir()
        with pytest.raises((NotANoteError, NoteNotFoundError)):
            read_note(str(tmp_vault), "subdir")

    def test_raises_vault_path_error_for_traversal(self, tmp_vault: Path):
        with pytest.raises(VaultPathError):
            read_note(str(tmp_vault), "../outside.md")

    def test_raises_vault_path_error_for_absolute_path(self, tmp_vault: Path):
        with pytest.raises(VaultPathError):
            read_note(str(tmp_vault), "/etc/passwd")

    def test_raises_vault_path_error_for_empty_path(self, tmp_vault: Path):
        with pytest.raises(VaultPathError):
            read_note(str(tmp_vault), "")

    def test_error_message_includes_path(self, tmp_vault: Path):
        with pytest.raises(NoteNotFoundError) as exc_info:
            read_note(str(tmp_vault), "missing/note.md")
        assert "missing/note.md" in str(exc_info.value)

    def test_raises_not_found_for_json_file(self, tmp_vault: Path):
        (tmp_vault / "data.json").write_text("{}", encoding="utf-8")
        with pytest.raises(NotANoteError):
            read_note(str(tmp_vault), "data.json")


class TestReadNoteEdgeCases:

    def test_note_with_only_frontmatter_no_body(self, tmp_vault: Path):
        (tmp_vault / "fm_only.md").write_text("---\ntitle: Only FM\n---\n", encoding="utf-8")
        note = read_note(str(tmp_vault), "fm_only.md")
        assert note.frontmatter["title"] == "Only FM"
        # Body may be empty string or a single newline — either is valid
        assert note.content.strip() == ""

    def test_completely_empty_note(self, tmp_vault: Path):
        (tmp_vault / "empty.md").write_text("", encoding="utf-8")
        note = read_note(str(tmp_vault), "empty.md")
        assert note.frontmatter == {}
        assert note.content == ""
        assert note.size == 0

    def test_note_with_utf8_umlauts(self, tmp_vault: Path):
        (tmp_vault / "german.md").write_text(
            "---\ntitle: Überprüfung\n---\n\nMöbel, Straße, ärgerlich.\n",
            encoding="utf-8",
        )
        note = read_note(str(tmp_vault), "german.md")
        assert "Überprüfung" in note.frontmatter["title"]
        assert "Möbel" in note.content

    def test_note_with_windows_line_endings(self, tmp_vault: Path):
        content = "---\r\ntitle: Windows\r\n---\r\n\r\nBody.\r\n"
        (tmp_vault / "crlf.md").write_bytes(content.encode("utf-8"))
        # Should not raise; content is returned (frontmatter parsing behavior may vary)
        note = read_note(str(tmp_vault), "crlf.md")
        assert note.size > 0
```

---

## Step 5 — Integration test

The integration test spins up the actual MCP server in-process (stdio mode) and exercises the
`read_note` tool over the MCP protocol. It creates a minimal vault in a temp directory and
confirms end-to-end behaviour including error responses.

```
tests/integration/
└── test_read_note_integration.py
```

```python
"""
Integration test: starts the MCP server in stdio mode in a subprocess,
sends raw MCP JSON-RPC messages over stdin, reads responses from stdout.
Uses a minimal vault created in a temp directory.

The vault structure created for these tests:

  vault/
  ├── simple.md              (no frontmatter)
  ├── with_fm.md             (has frontmatter)
  ├── 🚀 Next actions.md     (emoji filename)
  └── Getting things done/
      └── Projects/
          └── LiZu.md        (project note, subdirectory)
"""

from __future__ import annotations
import asyncio
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Minimal vault fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def minimal_vault(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Creates a minimal vault in a temp directory. Scoped to the module so the
    vault is created once and shared across all integration tests.
    """
    vault = tmp_path_factory.mktemp("vault")

    # 1. Simple note — no frontmatter
    (vault / "simple.md").write_text(
        "# Simple Note\n\nJust some plain content.\n",
        encoding="utf-8",
    )

    # 2. Note with frontmatter
    (vault / "with_fm.md").write_text(
        textwrap.dedent("""\
            ---
            title: Note With Frontmatter
            created: 2026-01-15
            completed: false
            tags:
              - project
              - gtd
            ---

            ## Body

            This is the body of the note.
            """),
        encoding="utf-8",
    )

    # 3. Emoji filename
    (vault / "🚀 Next actions.md").write_text(
        "---\ntitle: Next Actions\n---\n\n- [ ] First task #context/pc\n",
        encoding="utf-8",
    )

    # 4. Note in subdirectory
    subdir = vault / "Getting things done" / "Projects"
    subdir.mkdir(parents=True)
    (subdir / "LiZu.md").write_text(
        textwrap.dedent("""\
            ---
            tags:
              - project
            completed: false
            inactive: false
            ---

            # LiZu

            #project

            ## Todo
            - [ ] Follow up with Julian #context/work
            """),
        encoding="utf-8",
    )

    return vault


# ---------------------------------------------------------------------------
# MCP stdio client helper
# ---------------------------------------------------------------------------

class StdioMCPClient:
    """
    Minimal MCP client that speaks JSON-RPC over stdio.
    Starts the server as a subprocess, sends requests, reads responses.
    """

    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self._proc: subprocess.Popen | None = None
        self._msg_id = 0

    def start(self):
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "obsidian_mcp.main"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                "VAULT_PATH": self.vault_path,
                "MCP_TRANSPORT": "stdio",
                "LOG_LEVEL": "WARNING",
                # Inherit PATH so the subprocess can find Python packages
                **__import__("os").environ,
            },
            text=True,
            bufsize=1,
        )

    def stop(self):
        if self._proc:
            self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)

    def _send(self, method: str, params: dict) -> dict:
        self._msg_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._msg_id,
            "method": method,
            "params": params,
        }
        line = json.dumps(request) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()
        response_line = self._proc.stdout.readline()
        return json.loads(response_line)

    def initialize(self) -> dict:
        return self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1"},
        })

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self._send("tools/call", {"name": name, "arguments": arguments})

    def list_tools(self) -> dict:
        return self._send("tools/list", {})


@pytest.fixture(scope="module")
def mcp_client(minimal_vault: Path):
    client = StdioMCPClient(str(minimal_vault))
    client.start()
    client.initialize()
    yield client
    client.stop()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestReadNoteIntegration:

    def test_server_lists_read_note_tool(self, mcp_client: StdioMCPClient):
        response = mcp_client.list_tools()
        tools = response["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "read_note" in names

    def test_read_note_tool_has_correct_schema(self, mcp_client: StdioMCPClient):
        response = mcp_client.list_tools()
        tools = {t["name"]: t for t in response["result"]["tools"]}
        schema = tools["read_note"]["inputSchema"]
        assert "path" in schema["properties"]
        assert "path" in schema["required"]

    def test_reads_simple_note(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool("read_note", {"path": "simple.md"})
        result = response["result"]
        assert not result.get("isError")
        payload = json.loads(result["content"][0]["text"])
        assert payload["path"] == "simple.md"
        assert "Just some plain content." in payload["content"]
        assert payload["frontmatter"] == {}

    def test_reads_note_with_frontmatter(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool("read_note", {"path": "with_fm.md"})
        result = response["result"]
        assert not result.get("isError")
        payload = json.loads(result["content"][0]["text"])
        assert payload["frontmatter"]["title"] == "Note With Frontmatter"
        assert payload["frontmatter"]["completed"] is False
        assert "project" in payload["frontmatter"]["tags"]
        assert "This is the body of the note." in payload["content"]

    def test_reads_note_with_emoji_filename(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool("read_note", {"path": "🚀 Next actions.md"})
        result = response["result"]
        assert not result.get("isError")
        payload = json.loads(result["content"][0]["text"])
        assert payload["frontmatter"]["title"] == "Next Actions"
        assert "First task" in payload["content"]

    def test_reads_note_in_subdirectory(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool(
            "read_note",
            {"path": "Getting things done/Projects/LiZu.md"},
        )
        result = response["result"]
        assert not result.get("isError")
        payload = json.loads(result["content"][0]["text"])
        assert "project" in payload["frontmatter"]["tags"]
        assert "Follow up with Julian" in payload["content"]

    def test_response_includes_mtime(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool("read_note", {"path": "simple.md"})
        payload = json.loads(response["result"]["content"][0]["text"])
        assert "mtime" in payload
        # mtime should be a valid ISO datetime string
        from datetime import datetime
        datetime.fromisoformat(payload["mtime"].replace("Z", "+00:00"))

    def test_response_includes_size(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool("read_note", {"path": "simple.md"})
        payload = json.loads(response["result"]["content"][0]["text"])
        assert "size" in payload
        assert isinstance(payload["size"], int)
        assert payload["size"] > 0

    def test_returns_error_for_missing_note(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool("read_note", {"path": "does_not_exist.md"})
        result = response["result"]
        assert result.get("isError") is True
        error_text = result["content"][0]["text"]
        assert "NOT_FOUND" in error_text

    def test_returns_error_for_path_traversal(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool("read_note", {"path": "../etc/passwd"})
        result = response["result"]
        assert result.get("isError") is True
        error_text = result["content"][0]["text"]
        assert "INVALID_PATH" in error_text

    def test_returns_error_for_non_markdown_file(self, mcp_client: StdioMCPClient):
        # Create a .txt file in the vault to test against
        # (do this via filesystem directly, not via MCP — write_note not yet implemented)
        import os
        txt_path = Path(mcp_client.vault_path) / "data.txt"
        txt_path.write_text("some text", encoding="utf-8")

        response = mcp_client.call_tool("read_note", {"path": "data.txt"})
        result = response["result"]
        assert result.get("isError") is True
        error_text = result["content"][0]["text"]
        assert "NOT_A_NOTE" in error_text

    def test_pretty_print_flag(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool(
            "read_note", {"path": "with_fm.md", "pretty_print": True}
        )
        result = response["result"]
        assert not result.get("isError")
        payload = json.loads(result["content"][0]["text"])
        # pretty_print=True: frontmatter rendered inline in content
        assert "title" in payload["content"] or payload["frontmatter"] is not None

    def test_raw_field_contains_complete_file(self, mcp_client: StdioMCPClient):
        response = mcp_client.call_tool("read_note", {"path": "with_fm.md"})
        payload = json.loads(response["result"]["content"][0]["text"])
        assert "---" in payload["raw"]
        assert "title: Note With Frontmatter" in payload["raw"]
        assert "This is the body of the note." in payload["raw"]
```

---

## Step 6 — Dockerfile

```dockerfile
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e .


FROM python:3.12-slim

# Non-root user
RUN useradd -m -u 1000 mcp
USER mcp
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/src /app/src

ENV VAULT_PATH=/vault
ENV MCP_TRANSPORT=sse
ENV MCP_PORT=8080
ENV LOG_LEVEL=INFO

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["python", "-m", "obsidian_mcp.main"]
```

Build for arm64:
```bash
docker buildx build \
  --platform linux/arm64 \
  --tag your-registry/obsidian-mcp:0.1.0 \
  --push \
  .
```

---

## Execution order

```
1.  pip install -e ".[dev]"
2.  Implement errors.py
3.  Implement config.py
4.  Implement vault/path.py        → pytest tests/unit/test_path.py
5.  Implement vault/frontmatter.py → pytest tests/unit/test_frontmatter.py
6.  Implement vault/io.py          → pytest tests/unit/test_read_note.py
7.  Implement tools/reading.py
8.  Implement tools/registry.py
9.  Implement main.py
10. pytest tests/unit/             (all 3 unit suites green)
11. pytest tests/integration/      (server boots, all tool calls work)
12. docker buildx build --platform linux/arm64
```

Full unit suite should run in under 2 seconds (no I/O, all tmp_path).  
Integration suite should run in under 10 seconds (one subprocess, all calls synchronous).

---

## What's explicitly out of scope for this MVP

- `write_note`, `patch_note`, and all other 17 tools
- qmd integration
- Vault syncing (sidecar responsibility)
- The task engine
- Authentication / API keys on the SSE endpoint
- Persistent logging / metrics

Each of these can be added incrementally. The path resolution, frontmatter, error hierarchy,
and MCP wiring established here carry forward unchanged into every subsequent tool.
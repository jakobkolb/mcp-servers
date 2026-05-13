# Obsidian Vault MCP Server — Implementation Specification

**Version:** 1.0  
**Language:** Python 3.12+  
**Transport:** Streamable HTTP (primary), stdio (secondary)  
**Purpose:** Headless MCP server exposing 19 tools for reading, writing, searching, and task management against a local Obsidian vault. No Obsidian process required — operates directly on the markdown filesystem.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Dependencies](#2-dependencies)
3. [Configuration](#3-configuration)
4. [Vault Conventions](#4-vault-conventions)
5. [Core Abstractions](#5-core-abstractions)
6. [Tool Reference — Reading (5 tools)](#6-tool-reference--reading)
7. [Tool Reference — Searching (2 tools)](#7-tool-reference--searching)
8. [Tool Reference — Writing (4 tools)](#8-tool-reference--writing)
9. [Tool Reference — Organizing (3 tools)](#9-tool-reference--organizing)
10. [Tool Reference — Vault-wide (1 tool)](#10-tool-reference--vault-wide)
11. [Tool Reference — Tasks (4 tools)](#11-tool-reference--tasks)
12. [Task Parsing Specification](#12-task-parsing-specification)
13. [Project Sequencing Specification](#13-project-sequencing-specification)
14. [Frontmatter Handling](#14-frontmatter-handling)
15. [Patch Engine](#15-patch-engine)
16. [Link-Aware Move](#16-link-aware-move)
17. [Atomic Writes](#17-atomic-writes)
18. [Error Handling](#18-error-handling)
19. [Project Layout](#19-project-layout)
20. [Kubernetes Deployment](#20-kubernetes-deployment)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  MCP Transport Layer                                │
│  Streamable HTTP on :8080 /mcp (primary, k8s)      │
│  stdio              (secondary, Claude Desktop)     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  Tool Router  (19 tools)                            │
│  reading · searching · writing · organizing · tasks │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  Vault Service Layer                                │
│  ┌────────────┐ ┌────────────┐ ┌─────────────────┐ │
│  │ Frontmatter│ │   Patch    │ │  Task Engine    │ │
│  │  parser    │ │   engine   │ │  parser+collect │ │
│  └────────────┘ └────────────┘ └─────────────────┘ │
│  ┌────────────┐ ┌────────────┐ ┌─────────────────┐ │
│  │  Search    │ │    Link    │ │  Atomic writes  │ │
│  │  (BM25/re) │ │  rewriter  │ │  (tmp+replace)  │ │
│  └────────────┘ └────────────┘ └─────────────────┘ │
└──────────────────────┬──────────────────────────────┘
                       │
            PVC  /vault  (mounted RW)
```

The server owns the **write side** of the vault completely (write, patch, move, delete, task mutations). For semantic search, it can optionally delegate to a [qmd](https://github.com/tobi/qmd) sidecar via HTTP — but the server must work standalone with regex-based search when qmd is unavailable.

---

## 2. Dependencies

```toml
# pyproject.toml

[project]
name = "obsidian-mcp"
requires-python = ">=3.12"

dependencies = [
    # MCP framework
    "mcp[cli]>=1.0.0",           # official modelcontextprotocol Python SDK

    # Markdown + frontmatter parsing
    "python-frontmatter>=1.1.0", # parse/serialize YAML frontmatter + body

    # YAML serialization (preserves key order, avoids unwanted quoting)
    "ruamel.yaml>=0.18.0",

    # HTTP server (for Streamable HTTP transport on k8s)
    "starlette>=0.46.0",
    "uvicorn[standard]>=0.32.0",

    # Utilities
    "pydantic>=2.9.0",           # input validation for tool arguments
    "python-dateutil>=2.9.0",    # date parsing for task dates
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "mypy>=1.11",
    "ruff>=0.6",
]
```

**Standard library modules used heavily:**  
`pathlib`, `os`, `re`, `tempfile`, `shutil`, `stat`, `datetime`, `json`, `logging`, `asyncio`

---

## 3. Configuration

Configuration is read from environment variables, with a fallback YAML config file at `$VAULT_PATH/.mcp-server.yml`.

| Env var | Required | Default | Description |
|---|---|---|---|
| `VAULT_PATH` | yes | — | Absolute path to vault root on the PVC |
| `MCP_TRANSPORT` | no | `streamable-http` | `streamable-http` for HTTP at `/mcp`, `stdio` for stdin/stdout |
| `MCP_HOST` | no | `0.0.0.0` | Bind host (Streamable HTTP mode) |
| `MCP_PORT` | no | `8080` | Bind port (Streamable HTTP mode) |
| `QMD_URL` | no | — | Base URL of qmd HTTP MCP server (e.g. `http://qmd:8181`). If set, `search_notes` delegates semantic queries here |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING` |
| `SEARCH_LIMIT_MAX` | no | `20` | Hard ceiling on `search_notes` results |
| `MAX_BATCH_READ` | no | `10` | Max paths per `read_multiple_notes` call |

```python
# vault/config.py
from pydantic import BaseSettings

class Config(BaseSettings):
    vault_path: str
    mcp_transport: str = "streamable-http"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080
    qmd_url: str | None = None
    log_level: str = "INFO"
    search_limit_max: int = 20
    max_batch_read: int = 10

    class Config:
        env_file = ".env"
```

---

## 4. Vault Conventions

These are specific to the vault this server is built for. They inform default behaviors but must not be hardcoded — config should override them.

### Excluded from operations by default

```python
GLOBAL_EXCLUDE = {
    "folders": ["Utility"],
    "tags": ["#exclude-master-tasklist", "#completed"],
    "headings": [
        "Morgens - 2 Minuten Check In",
        "Abends - 10 Minuten Cleanup",
    ],
}
```

### Key paths

| Purpose | Path |
|---|---|
| Projects | `Getting things done/Projects/` |
| Completed projects | `Getting things done/Projects/Completed/` |
| Next Actions list | `Getting things done/🚀 Next actions list.md` |
| Waiting For list | `Getting things done/⏳ Waiting For.md` |
| Someday list | `Getting things done/💤 Someday.md` |
| Reviews | `Getting things done/Reviews/` |
| Project template | `Utility/Templates/New note templates/Project.md` |
| Voice/style prompt | `Utility/Prompts/Jakob Ton und Duktus.md` |
| GTD lessons | `Getting things done/Documentation/GTD Lessons Learned.md` |

### Task context tags used in the vault

`#context/pc`, `#context/work`, `#context/kids`, `#context/phone`, `#context/home`, `#context/errands`, `#context/reading`, `#context/watchlist`

---

## 5. Core Abstractions

### `VaultPath`

All paths in tool inputs/outputs are **vault-relative** strings (e.g., `"Diary/2026-05-12.md"`). The server resolves them against `VAULT_PATH` before any filesystem operation. 

```python
# vault/path.py

def resolve(vault_root: str, relative: str) -> Path:
    """Resolve a vault-relative path to absolute. Raises VaultPathError if it
    would escape the vault root (path traversal guard)."""
    root = Path(vault_root).resolve()
    full = (root / relative).resolve()
    if not str(full).startswith(str(root)):
        raise VaultPathError(f"Path escapes vault root: {relative!r}")
    return full

def to_relative(vault_root: str, absolute: Path) -> str:
    return str(absolute.relative_to(vault_root))
```

### `Note`

The parsed representation of a markdown file.

```python
@dataclass
class Note:
    path: str               # vault-relative
    frontmatter: dict       # parsed YAML, empty dict if none
    body: str               # content after the frontmatter block
    raw: str                # full file content (frontmatter + body)
    mtime: float            # file modification time (Unix timestamp)
    size: int               # file size in bytes
```

### `SearchResult`

```python
@dataclass
class SearchResult:
    path: str
    snippet: str            # ≤3 lines around the match
    score: float            # 0–1; 1.0 = exact match
    line: int               # line number of first match (1-indexed)
```

---

## 6. Tool Reference — Reading

### `read_note`

Read full content of a single note.

**Input schema:**
```python
class ReadNoteInput(BaseModel):
    path: str               # vault-relative path, must end in .md
    pretty_print: bool = False  # if true, strip frontmatter delimiters from output
```

**Output:**
```python
{
    "path": str,
    "frontmatter": dict,    # parsed YAML or {}
    "content": str,         # body text (after the --- block)
    "raw": str,             # full file content
    "mtime": str,           # ISO datetime of last modification
    "size": int,            # bytes
}
```

**Behavior:**
- If `pretty_print=True`, return `content` with frontmatter rendered as readable key: value lines at the top (no `---` delimiters), for display purposes. `raw` always contains the true file content.
- Raise `NoteNotFoundError` if path does not exist.
- Raise `NotANoteError` if path exists but is not a `.md` file.

---

### `read_multiple_notes`

Batch read up to `MAX_BATCH_READ` notes. The primary tool for the two-pass strategy.

**Input schema:**
```python
class ReadMultipleNotesInput(BaseModel):
    paths: list[str]           # max MAX_BATCH_READ (default 10) paths
    include_content: bool = True
    include_frontmatter: bool = True
```

**Output:**
```python
{
    "notes": [
        {
            "path": str,
            "frontmatter": dict | None,   # None if include_frontmatter=False
            "content": str | None,        # None if include_content=False
            "mtime": str,
            "size": int,
            "error": str | None,          # set if this specific path failed
        }
    ],
    "errors": int   # count of failed paths
}
```

**Behavior:**
- Per-note failures (missing file, permission error) are captured in `error` field and do not abort the batch.
- If `len(paths) > MAX_BATCH_READ`, raise `BatchTooLargeError` with the limit in the message.
- Reads are performed concurrently with `asyncio.gather`.

---

### `get_frontmatter`

Return only the YAML frontmatter of a note. ~5% the cost of a full read. Use for filter passes.

**Input schema:**
```python
class GetFrontmatterInput(BaseModel):
    path: str
```

**Output:**
```python
{
    "path": str,
    "frontmatter": dict   # empty dict if note has no frontmatter block
}
```

---

### `get_notes_info`

Return filesystem-level metadata without reading content. Use when only modification time or size is needed.

**Input schema:**
```python
class GetNotesInfoInput(BaseModel):
    paths: list[str]      # no batch limit; metadata reads are trivial
```

**Output:**
```python
{
    "notes": [
        {
            "path": str,
            "exists": bool,
            "mtime": str | None,        # ISO datetime
            "ctime": str | None,        # ISO datetime (creation time)
            "size": int | None,         # bytes
            "is_note": bool,            # True if .md file
        }
    ]
}
```

---

### `list_directory`

List files and subdirectories in a vault folder. Cheaper than `search_notes` when the folder is known.

**Input schema:**
```python
class ListDirectoryInput(BaseModel):
    path: str = ""          # vault-relative folder; "" = vault root
    recursive: bool = False
```

**Output:**
```python
{
    "path": str,            # the folder that was listed
    "files": [
        {
            "name": str,    # filename only
            "path": str,    # vault-relative full path
            "is_note": bool,
            "size": int,
            "mtime": str,
        }
    ],
    "directories": [
        {
            "name": str,
            "path": str,
        }
    ],
    "total_files": int,
    "total_dirs": int,
}
```

**Behavior:**
- Includes all files regardless of extension (markdown and non-markdown).
- When `recursive=False` (default), lists immediate children only.
- When `recursive=True`, returns the full subtree. Paths remain vault-relative.
- Hidden files (starting with `.`) are excluded.

---

## 7. Tool Reference — Searching

### `search_notes`

Full-text and/or frontmatter search across the vault.

**Input schema:**
```python
class SearchNotesInput(BaseModel):
    query: str
    search_content: bool = True
    search_frontmatter: bool = False
    case_sensitive: bool = False
    limit: int = 5          # max SEARCH_LIMIT_MAX (default 20)
    path_filter: str | None = None  # restrict to notes under this folder
```

**Output:**
```python
{
    "results": [
        {
            "path": str,
            "snippet": str,         # ≤3 lines of context around match
            "score": float,
            "line": int,
            "frontmatter_match": bool,
        }
    ],
    "total_found": int,     # total matches before limit
    "query": str,
    "search_mode": str,     # "regex" | "qmd_semantic" | "qmd_lex"
}
```

**Behavior:**

The server tries backends in order:

1. **qmd delegation** (if `QMD_URL` is set): POST to qmd's MCP `query` tool. Map `search_notes` parameters to qmd's interface. Return qmd results normalized to `SearchResult` shape.

2. **Regex fallback** (always available): Walk all `.md` files under `VAULT_PATH`, skip files in excluded folders, apply `re.search` (case flag derived from `case_sensitive`). Score is `1.0` for exact match, `0.5` for case-insensitive match.

**No built-in path filter.** The caller is responsible for filtering results by path prefix. The `path_filter` parameter is a convenience that pre-filters the walk — it does not guarantee results come only from that folder (qmd doesn't support this natively).

**Search does not filter excluded folders automatically.** The caller must discard results from `Completed/`, `Templates/`, etc. This mirrors the existing behavior clients are already adapted to.

---

### `list_all_tags`

Return all tags present in the vault (frontmatter `tags:` field and inline `#hashtags`), with occurrence counts.

**Input schema:** none

**Output:**
```python
{
    "tags": [
        {
            "tag": str,             # normalized, always with leading #
            "count": int,
            "sources": ["frontmatter", "inline"],
        }
    ],
    "total_unique": int,
}
```

**Behavior:**
- Frontmatter tags: parsed from `tags:` YAML field. Handles both `tags: [project, gtd]` and `tags:\n  - project` forms. Normalizes to `#project` form.
- Inline tags: regex `r'(?<!\w)#([a-zA-Z0-9_/\-äöüÄÖÜß]+)'` applied to body text. Excludes heading lines.
- Tags inside code blocks (between ` ``` `) are excluded.
- Results sorted by count descending, then alphabetically.

---

## 8. Tool Reference — Writing

### `write_note`

Create, overwrite, append to, or prepend to a note.

**Input schema:**
```python
class WriteNoteInput(BaseModel):
    path: str
    content: str
    mode: Literal["overwrite", "append", "prepend"] = "overwrite"
    create_dirs: bool = True   # create parent directories if missing
```

**Output:**
```python
{
    "path": str,
    "mode": str,
    "bytes_written": int,
    "created": bool,        # True if file did not exist before
}
```

**Behavior:**
- `overwrite`: write `content` as the complete file. Creates the file if it does not exist. **Embed YAML frontmatter as a `---` block at the top of `content`** — do not pass a separate `frontmatter` parameter (no such parameter exists on this tool by design, to prevent the known bad pattern).
- `append`: read existing content, concatenate `content` at the end, write back atomically. If file does not exist, create it.
- `prepend`: read existing content, prepend `content`, write back atomically. If file does not exist, create it.
- All writes are atomic: write to a `.tmp` sibling, then `os.replace()`.
- `create_dirs=True` (default): call `path.parent.mkdir(parents=True, exist_ok=True)` before writing.

---

### `patch_note`

Targeted string find-and-replace within a note. The primary tool for small edits.

**Input schema:**
```python
class PatchNoteInput(BaseModel):
    path: str
    old_string: str         # must match exactly (including whitespace)
    new_string: str
    replace_all: bool = False
```

**Output:**
```python
{
    "path": str,
    "replacements": int,    # number of substitutions made
    "old_string_length": int,
    "new_string_length": int,
}
```

**Behavior:** See [Section 15 — Patch Engine](#15-patch-engine).

**Known issue — emoji in paths:** Paths containing emoji characters (e.g., `📝 Note.md`, `🚀 Next actions list.md`) can cause encoding mismatches when `old_string` is matched against the file content read via `pathlib`. **Workaround:** read the file in binary mode, encode `old_string` to UTF-8, do the replacement on bytes, decode and write back. This must be the default code path for all patch operations.

```python
# Always work in bytes to handle emoji paths and emoji content
content_bytes = path.read_bytes()
old_bytes = old_string.encode("utf-8")
new_bytes = new_string.encode("utf-8")
count = content_bytes.count(old_bytes)
# ... check count, replace, write
```

---

### `update_frontmatter`

Merge or replace frontmatter fields on an existing note, preserving body content.

**Input schema:**
```python
class UpdateFrontmatterInput(BaseModel):
    path: str
    frontmatter: dict       # fields to set/update
    merge: bool = True      # True: merge with existing; False: replace entirely
```

**Output:**
```python
{
    "path": str,
    "fields_updated": list[str],
    "fields_added": list[str],
    "frontmatter_after": dict,
}
```

**Behavior:**
- Parse existing frontmatter from the file.
- If `merge=True`: update existing dict with input dict (shallow merge).
- If `merge=False`: replace frontmatter entirely with input dict.
- Serialize back using `ruamel.yaml` with block style to preserve readability.
- Write the new frontmatter + original body atomically.
- If the file has no frontmatter block, create one.

**Serialization rules (via ruamel.yaml):**
- `block_seq_indent: 2`, `best_map_flow_style: False`
- Dates and datetimes: serialize as bare YAML scalars, not quoted strings. `completed: 2026-04-30T10:00:00` not `completed: "2026-04-30T10:00:00"`.
- Boolean values: `true`/`false` (lowercase), not `True`/`False`.
- Do not add `!!python/object` tags.

---

### `manage_tags`

Add or remove tags in the frontmatter `tags:` field of a note.

**Input schema:**
```python
class ManageTagsInput(BaseModel):
    path: str
    operation: Literal["add", "remove", "list"]
    tags: list[str] = []    # required for add/remove; ignored for list
```

**Output:**
```python
{
    "path": str,
    "operation": str,
    "tags_before": list[str],
    "tags_after": list[str],       # None for "list" operation
    "tags_added": list[str],
    "tags_removed": list[str],
}
```

**Behavior:**
- Operates only on frontmatter `tags:` field. For inline `#tags` in body text, use `patch_note`.
- Tags are normalized: strip leading `#` before storing in frontmatter (Obsidian stores them without `#` in the `tags:` field, but accepts both).
- `add`: union of existing tags and new tags. Deduplicates. Preserves existing order; appends new tags at end.
- `remove`: set difference. Case-insensitive comparison.
- `list`: return current tags, no write.

---

## 9. Tool Reference — Organizing

### `move_note`

Move or rename a `.md` note, rewriting all `[[wiki-links]]` that reference it across the vault.

**Input schema:**
```python
class MoveNoteInput(BaseModel):
    source: str             # vault-relative current path
    destination: str        # vault-relative target path
    create_dirs: bool = True
```

**Output:**
```python
{
    "source": str,
    "destination": str,
    "links_rewritten": int,     # number of files where links were updated
    "files_scanned": int,
}
```

**Behavior:** See [Section 16 — Link-Aware Move](#16-link-aware-move).

---

### `move_file`

Move any file (not necessarily a `.md` note). Does **not** rewrite wiki-links. Binary-safe.

**Input schema:**
```python
class MoveFileInput(BaseModel):
    source: str
    destination: str
    create_dirs: bool = True
```

**Output:**
```python
{
    "source": str,
    "destination": str,
}
```

**Behavior:**
- Uses `shutil.move()` — works across filesystem boundaries.
- Does not scan or rewrite any links.
- Use `move_note` for `.md` files unless you explicitly do not want link rewriting.

---

### `delete_note`

Delete a markdown note. Irreversible.

**Input schema:**
```python
class DeleteNoteInput(BaseModel):
    path: str
    confirm: bool = False   # must be True to proceed; a safety gate
```

**Output:**
```python
{
    "path": str,
    "deleted": bool,
    "message": str,
}
```

**Behavior:**
- If `confirm=False` (default), return `{"deleted": false, "message": "Set confirm=true to proceed with deletion of '<path>'"}`. Do not delete.
- If `confirm=True`, delete the file and return `{"deleted": true}`.
- Raise `NoteNotFoundError` if path does not exist.
- Does not rewrite backlinks — callers should call `search_notes("[[<title>]]")` first if they want to audit backlinks before deletion.

---

## 10. Tool Reference — Vault-wide

### `get_vault_stats`

Return aggregate statistics about the vault.

**Input schema:** none

**Output:**
```python
{
    "total_notes": int,
    "total_files": int,         # includes non-.md files
    "total_dirs": int,
    "total_size_bytes": int,
    "recently_modified": [      # top 10 by mtime
        {"path": str, "mtime": str}
    ],
    "vault_path": str,
    "generated_at": str,        # ISO datetime
}
```

---

## 11. Tool Reference — Tasks

These four tools implement the task management layer on top of the vault's markdown format. They understand the Obsidian Tasks plugin emoji syntax and the GTD project sequencing convention.

### `get_tasks`

The primary task query tool. Implements the full collection and grouping logic from `tasks.js`. Returns structured task data for any downstream processing.

**Input schema:**
```python
class GetTasksInput(BaseModel):
    context_tag: str | None = None
        # Filter to tasks carrying this tag, e.g. "#context/pc".
        # None returns all contexts.

    group: Literal["priority", "waiting", "normal", "notag", "someday"] | None = None
        # Filter to a specific group. None returns all groups.

    hide_future_scheduled: bool = True
        # When True, tasks with ⏳ date > today are excluded.

    include_someday: bool = False
        # When False, Someday group is excluded. Reduces noise in daily views.

    include_waiting: bool = True
        # When False, Waiting group is excluded.

    project_tasks_only: bool = False
        # When True, only tasks from project notes are returned.

    exclude_projects: bool = False
        # When True, tasks from project notes are excluded (non-project only).
```

**Output:**
```python
{
    "tasks": [
        {
            # Identity
            "path": str,            # vault-relative file path
            "line": int,            # 1-indexed line number in file
            "raw_line": str,        # full original task line

            # Content
            "text": str,            # task text with emoji metadata stripped
            "tags": list[str],      # all #tags found in task text (normalized, with #)

            # Dates (all "YYYY-MM-DD" strings or null)
            "due_date": str | None,
            "scheduled_date": str | None,   # ⏳
            "start_date": str | None,       # 🛫
            "created_date": str | None,     # ➕

            # Priority
            "priority": str,        # "highest"|"high"|"medium"|"low"|"lowest"|""

            # Recurrence
            "recurrence": str,      # raw recurrence string, e.g. "every week", or ""

            # Grouping
            "group": str,           # "priority"|"waiting"|"normal"|"notag"|"someday"
            "sort_date_ms": int,    # Unix ms for sorting; derived from ➕, page created, or ctime

            # Project context (null if task is not from a project note)
            "project_name": str | None,
            "project_path": str | None,
            "project_section": str | None,  # heading under which the task falls
            "is_sequenced": bool,           # True if task sequencing was applied
        }
    ],

    "projects_without_next_action": [
        {
            "name": str,
            "path": str,
        }
    ],

    "total_tasks": int,
    "generated_at": str,        # ISO datetime; client can check freshness
}
```

**Behavior:** See [Section 12 — Task Parsing](#12-task-parsing-specification) and [Section 13 — Project Sequencing](#13-project-sequencing-specification).

**Group assignment logic:**

```python
def assign_group(task: RawTask, page_tags: list[str]) -> str:
    if "#someday" in task.tags:
        return "someday"
    if "#waiting-on" in task.tags:
        return "waiting"
    if "🔼" in task.raw_line or "#🔼" in page_tags:
        return "priority"
    if len(task.tags) == 0:
        return "notag"
    return "normal"
```

**Sort date resolution (in priority order):**

```python
def resolve_sort_date(task: RawTask, page_fm: dict, page_ctime: float) -> int:
    if task.created_date:
        return int(datetime.fromisoformat(task.created_date).timestamp() * 1000)
    if "created" in page_fm:
        val = page_fm["created"]
        # val may be a datetime object (ruamel parses it) or string
        if hasattr(val, "timestamp"):
            return int(val.timestamp() * 1000)
        return int(datetime.fromisoformat(str(val)).timestamp() * 1000)
    return int(page_ctime * 1000)
```

**Global exclude application:**

```python
def should_exclude_file(path: str, page_fm: dict) -> bool:
    # Folder exclusion
    for folder in GLOBAL_EXCLUDE["folders"]:
        if path.startswith(folder + "/") or path.startswith(folder + "\\"):
            return True
    # Tag exclusion
    page_tags = extract_tags(page_fm)
    for tag in GLOBAL_EXCLUDE["tags"]:
        if tag in page_tags or tag.lstrip("#") in page_tags:
            return True
    return False
```

---

### `complete_task`

Mark an open task as done. Patches `- [ ]` → `- [x]` and inserts `✅ YYYY-MM-DD`.

**Input schema:**
```python
class CompleteTaskInput(BaseModel):
    path: str
    line: int               # 1-indexed, from get_tasks result
    done_date: str | None = None  # "YYYY-MM-DD"; defaults to today (UTC)
```

**Output:**
```python
{
    "path": str,
    "line": int,
    "task_text": str,       # text of the completed task
    "done_date": str,
    "patched": bool,
}
```

**Behavior:**
1. Read the file.
2. Verify that line `line` contains `- [ ]` (open task marker). If it contains something else, raise `TaskStateError` with the actual line content. This guards against stale `line` numbers.
3. Build `done_date` string (today if not provided).
4. Construct the replacement: change `- [ ]` to `- [x]`, append `✅ YYYY-MM-DD` at end of the task text, before any trailing newline.
5. Patch via the patch engine (line-targeted, not full-content search).

**Completion date insertion position:**

The `✅` date is appended after all other content on the task line, before the newline:

```
- [ ] Buy milk #context/home ➕2024-01-01 ⏳2026-05-01
→
- [x] Buy milk #context/home ➕2024-01-01 ⏳2026-05-01 ✅2026-05-12
```

---

### `set_task_date`

Set, update, or remove a date emoji field on a task. The primary tool for deferring or scheduling tasks.

**Input schema:**
```python
class SetTaskDateInput(BaseModel):
    path: str
    line: int               # 1-indexed
    date_type: Literal["due", "scheduled", "start", "created"]
    date: str | None        # "YYYY-MM-DD"; None removes the field
```

**Output:**
```python
{
    "path": str,
    "line": int,
    "date_type": str,
    "date_before": str | None,
    "date_after": str | None,
    "patched": bool,
}
```

**Date emoji mapping:**

```python
DATE_EMOJI = {
    "due":       "📅",
    "scheduled": "⏳",
    "start":     "🛫",
    "created":   "➕",
}
DATE_PATTERN = {
    "due":       re.compile(r"📅\s?(\d{4}-\d{2}-\d{2})"),
    "scheduled": re.compile(r"⏳\s?(\d{4}-\d{2}-\d{2})"),
    "start":     re.compile(r"🛫\s?(\d{4}-\d{2}-\d{2})"),
    "created":   re.compile(r"➕\s?(\d{4}-\d{2}-\d{2})"),
}
```

**Behavior:**
1. Read file, isolate line `line`.
2. Check if the emoji field already exists on that line using `DATE_PATTERN[date_type]`.
3. If exists and `date` is not None: replace in-place using `re.sub`.
4. If exists and `date` is None: remove the emoji+date substring.
5. If absent and `date` is not None: append `{emoji} {date}` at end of task text (before newline).
6. Write back via patch engine.

---

### `add_task`

Append a new task to a file, with proper emoji metadata formatting.

**Input schema:**
```python
class AddTaskInput(BaseModel):
    path: str
    text: str               # task description text (no emoji needed)
    tags: list[str] = []    # e.g. ["#context/pc", "#waiting-on"]
    scheduled_date: str | None = None   # ⏳
    due_date: str | None = None         # 📅
    start_date: str | None = None       # 🛫
    priority: Literal["highest", "high", "medium", "low", "lowest", ""] = ""
    stamp_created: bool = True          # append ➕ YYYY-MM-DD
    append_under_heading: str | None = None
        # If set, insert after the last task under this heading.
        # If heading not found, append to end of file.
```

**Output:**
```python
{
    "path": str,
    "task_line": str,       # the formatted task line that was written
    "line": int,            # line number where it was inserted
    "created": bool,        # True if file was created
}
```

**Task line assembly:**

```python
PRIORITY_EMOJI = {
    "highest": "🔺",
    "high":    "⏫",
    "medium":  "🔼",
    "low":     "🔽",
    "lowest":  "⏬",
    "":        "",
}

def build_task_line(input: AddTaskInput) -> str:
    parts = [f"- [ ] {input.text}"]
    if input.tags:
        parts.append(" ".join(input.tags))
    if input.priority:
        parts.append(PRIORITY_EMOJI[input.priority])
    if input.stamp_created:
        parts.append(f"➕{date.today().isoformat()}")
    if input.scheduled_date:
        parts.append(f"⏳{input.scheduled_date}")
    if input.due_date:
        parts.append(f"📅{input.due_date}")
    if input.start_date:
        parts.append(f"🛫{input.start_date}")
    return " ".join(parts)
```

**`append_under_heading` behavior:**
1. Read file content.
2. Locate the target heading line.
3. Find the last task line (`- [ ]` or `- [x]`) under that heading (before the next heading of equal or higher level).
4. Insert the new task line after it.
5. If no tasks exist under the heading yet, insert after the heading line itself.
6. Atomic write.

If `append_under_heading` is None, append to end of file (same as `write_note(mode="append")`).

---

## 12. Task Parsing Specification

### Regex patterns

All task line parsing uses compiled regexes. Emoji must be matched as literal Unicode characters.

```python
import re

# Task line: captures indent, status, text
TASK_LINE_RE = re.compile(
    r'^(?P<indent>\s*)'
    r'- \[(?P<status>[x/ >\-])\] '
    r'(?P<text>.+)$'
)

# Date fields
DATE_RE = {
    "due":       re.compile(r"📅\s?(\d{4}-\d{2}-\d{2})"),
    "scheduled": re.compile(r"⏳\s?(\d{4}-\d{2}-\d{2})"),
    "start":     re.compile(r"🛫\s?(\d{4}-\d{2}-\d{2})"),
    "created":   re.compile(r"➕\s?(\d{4}-\d{2}-\d{2})"),
    "done":      re.compile(r"✅\s?(\d{4}-\d{2}-\d{2})"),
}

# Recurrence
RECURRENCE_RE = re.compile(r"🔁\s?([^📅⏳🛫➕✅🔁\n]+)")

# Inline tags (handles German umlauts)
INLINE_TAG_RE = re.compile(r'(?<!\w)#([a-zA-Z0-9_/\-äöüÄÖÜß]+)')

# Priority emoji (order matters: check longest/highest first)
PRIORITY_MAP = [
    ("🔺", "highest"),
    ("⏫", "high"),
    ("🔼", "medium"),
    ("🔽", "low"),
    ("⏬", "lowest"),
]
```

### `RawTask` dataclass

```python
@dataclass
class RawTask:
    # Source location
    path: str           # vault-relative
    line: int           # 1-indexed
    raw_line: str       # full original line text

    # Parsed fields
    status: str         # " " = open, "x" = done, "/" = in-progress,
                        # "-" = cancelled, ">" = forwarded
    text: str           # task text with all emoji metadata stripped

    tags: list[str]     # all #tags, normalized with leading #
    priority: str       # see PRIORITY_MAP above, "" if none

    due_date: str | None
    scheduled_date: str | None
    start_date: str | None
    created_date: str | None
    done_date: str | None
    recurrence: str     # "" if none

    # Set by collector
    section: str        # heading text above this task, "" if none/root
    page_tags: list[str]  # frontmatter tags from the containing note
    page_ctime: float   # file ctime Unix timestamp
    page_created: str | None  # page frontmatter 'created' field
```

### `parse_task_line(line: str, path: str, lineno: int) -> RawTask | None`

```python
def parse_task_line(line: str, path: str, lineno: int) -> RawTask | None:
    m = TASK_LINE_RE.match(line)
    if not m:
        return None

    raw_text = m.group("text")
    status = m.group("status")

    # Extract dates
    dates = {}
    for field, pattern in DATE_RE.items():
        dm = pattern.search(raw_text)
        dates[field] = dm.group(1) if dm else None

    # Extract recurrence
    rm = RECURRENCE_RE.search(raw_text)
    recurrence = rm.group(1).strip() if rm else ""

    # Extract priority
    priority = ""
    for emoji, level in PRIORITY_MAP:
        if emoji in raw_text:
            priority = level
            break

    # Extract tags (before stripping metadata)
    tags = [f"#{t}" for t in INLINE_TAG_RE.findall(raw_text)]

    # Strip all emoji metadata from text for display
    clean_text = raw_text
    for pattern in DATE_RE.values():
        clean_text = pattern.sub("", clean_text)
    clean_text = RECURRENCE_RE.sub("", clean_text)
    for emoji, _ in PRIORITY_MAP:
        clean_text = clean_text.replace(emoji, "")
    clean_text = clean_text.strip()

    return RawTask(
        path=path, line=lineno, raw_line=line, status=status,
        text=clean_text, tags=tags, priority=priority,
        due_date=dates["due"], scheduled_date=dates["scheduled"],
        start_date=dates["start"], created_date=dates["created"],
        done_date=dates["done"], recurrence=recurrence,
        section="", page_tags=[], page_ctime=0.0, page_created=None,
    )
```

### File-level task collection

```python
def collect_tasks_from_file(
    vault_root: str,
    rel_path: str,
    page_fm: dict,
    page_ctime: float,
) -> list[RawTask]:
    abs_path = Path(vault_root) / rel_path
    content = abs_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    page_tags = extract_tags(page_fm)
    page_created = str(page_fm.get("created", "")) or None

    current_section = ""
    tasks = []

    for i, line in enumerate(lines, start=1):
        # Track current heading
        heading_match = re.match(r'^#{1,6}\s+(.+)$', line)
        if heading_match:
            current_section = heading_match.group(1).strip()
            continue

        # Skip lines inside code blocks
        if line.startswith("```"):
            # toggle in_code_block — implement with a boolean flag
            continue

        task = parse_task_line(line, rel_path, i)
        if task and task.status == " ":  # only open tasks
            task.section = current_section
            task.page_tags = page_tags
            task.page_ctime = page_ctime
            task.page_created = page_created
            tasks.append(task)

    return tasks
```

### Future scheduled task check

```python
def is_future_scheduled(task: RawTask) -> bool:
    if not task.scheduled_date:
        return False
    scheduled = date.fromisoformat(task.scheduled_date)
    return scheduled > date.today()
```

---

## 13. Project Sequencing Specification

This implements the core GTD behavior from `tasks.js`: from a project note, only the **first uncompleted task per section heading** is surfaced. This models task sequencing — you can only "do" the next task in a sequence.

### Project detection

A note is a project note if its frontmatter `tags` field contains `"project"` or `"#project"` (case-insensitive), AND `completed` is not `True`, AND `inactive` is not `True`.

```python
def is_project_note(fm: dict) -> bool:
    tags = extract_tags(fm)
    has_project_tag = any(
        t.lower() in ("project", "#project") for t in tags
    )
    return (
        has_project_tag
        and not fm.get("completed", False)
        and not fm.get("inactive", False)
    )
```

### Sequencing algorithm

```python
def apply_project_sequencing(tasks: list[RawTask]) -> list[RawTask]:
    """
    Given all open tasks from a single project note (in file order),
    return only the first task per section.

    Exceptions:
    - Sections whose name contains "🟰" bypass sequencing (all tasks included).
    - Sections whose name contains "exclude" (case-insensitive) are skipped entirely.
    - The root section (no heading above task) counts as one section named "root".
    """
    seen_sections: set[str] = set()
    result: list[RawTask] = []

    for task in tasks:
        section = task.section if task.section else "root"

        if "exclude" in section.lower():
            continue

        if "🟰" in section:
            # No sequencing for parallel sections
            result.append(task)
            continue

        if section not in seen_sections:
            seen_sections.add(section)
            result.append(task)
        # else: skip — earlier task in this section takes priority

    return result
```

### Project task processing (full flow)

```python
def process_project_note(
    vault_root: str, rel_path: str, page_fm: dict, page_ctime: float
) -> tuple[list[RawTask], bool]:
    """
    Returns (tasks_to_surface, has_next_action).
    has_next_action is False when the project has no open tasks at all.
    """
    all_tasks = collect_tasks_from_file(vault_root, rel_path, page_fm, page_ctime)
    open_tasks = [t for t in all_tasks if t.status == " "]

    if not open_tasks:
        return [], False

    sequenced = apply_project_sequencing(open_tasks)
    return sequenced, True
```

### Non-project task processing

```python
def process_non_project_note(
    vault_root: str, rel_path: str, page_fm: dict, page_ctime: float,
    excluded_headings: list[str],
) -> list[RawTask]:
    all_tasks = collect_tasks_from_file(vault_root, rel_path, page_fm, page_ctime)
    return [
        t for t in all_tasks
        if t.status == " "
        and "#exclude" not in t.tags
        and t.section not in excluded_headings
        and "exclude" not in t.section.lower()
    ]
```

### Full vault task collection (`get_tasks` implementation)

```python
async def collect_all_tasks(config: Config, input: GetTasksInput) -> GetTasksOutput:
    vault = Path(config.vault_path)
    tasks: list[TaskResult] = []
    projects_without_na: list[dict] = []

    for md_file in vault.rglob("*.md"):
        rel_path = str(md_file.relative_to(vault))

        # Parse frontmatter (cheap)
        fm = parse_frontmatter(md_file)
        page_ctime = md_file.stat().st_ctime

        # Global exclude check
        if should_exclude_file(rel_path, fm):
            continue

        if is_project_note(fm):
            raw_tasks, has_na = process_project_note(
                config.vault_path, rel_path, fm, page_ctime
            )
            if not has_na:
                name = md_file.stem
                projects_without_na.append({"name": name, "path": rel_path})
        else:
            raw_tasks = process_non_project_note(
                config.vault_path, rel_path, fm, page_ctime,
                GLOBAL_EXCLUDE["headings"]
            )

        for raw in raw_tasks:
            if input.hide_future_scheduled and is_future_scheduled(raw):
                continue

            group = assign_group(raw, raw.page_tags)

            if input.group and group != input.group:
                continue
            if not input.include_someday and group == "someday":
                continue
            if not input.include_waiting and group == "waiting":
                continue
            if input.context_tag and input.context_tag not in raw.tags:
                continue
            if input.project_tasks_only and not raw.section:  # crude; refine if needed
                continue

            sort_date = resolve_sort_date(raw, fm, page_ctime)

            tasks.append(TaskResult(
                path=rel_path, line=raw.line, raw_line=raw.raw_line,
                text=raw.text, tags=raw.tags,
                due_date=raw.due_date, scheduled_date=raw.scheduled_date,
                start_date=raw.start_date, created_date=raw.created_date,
                priority=raw.priority, recurrence=raw.recurrence,
                group=group, sort_date_ms=sort_date,
                project_name=Path(rel_path).stem if is_project_note(fm) else None,
                project_path=rel_path if is_project_note(fm) else None,
                project_section=raw.section or None,
                is_sequenced=is_project_note(fm),
            ))

    # Sort: group order (waiting=0, priority=1, normal=2, notag=3, someday=4)
    # then ascending by sort_date
    GROUP_ORDER = {"waiting": 0, "priority": 1, "normal": 2, "notag": 3, "someday": 4}
    tasks.sort(key=lambda t: (GROUP_ORDER.get(t.group, 99), t.sort_date_ms))

    return GetTasksOutput(
        tasks=tasks,
        projects_without_next_action=projects_without_na,
        total_tasks=len(tasks),
        generated_at=datetime.utcnow().isoformat() + "Z",
    )
```

---

## 14. Frontmatter Handling

### Parsing

Use `python-frontmatter` for reading:

```python
import frontmatter as fm_lib

def parse_note(path: Path) -> Note:
    raw = path.read_text(encoding="utf-8", errors="replace")
    post = fm_lib.loads(raw)
    return Note(
        path=str(path),
        frontmatter=dict(post.metadata),
        body=post.content,
        raw=raw,
        mtime=path.stat().st_mtime,
        size=path.stat().st_size,
    )
```

### Serialization

Use `ruamel.yaml` for writing frontmatter (preserves formatting, avoids unwanted quoting of dates):

```python
from ruamel.yaml import YAML

def serialize_frontmatter(fm: dict) -> str:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.best_map_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 120

    from io import StringIO
    stream = StringIO()
    yaml.dump(fm, stream)
    return stream.getvalue()

def build_note_content(fm: dict | None, body: str) -> str:
    if not fm:
        return body
    fm_text = serialize_frontmatter(fm)
    return f"---\n{fm_text}---\n{body}"
```

### Tag normalization

Obsidian stores frontmatter tags **without** the leading `#`:

```yaml
tags:
  - project
  - gtd
```

But inline body tags use `#`. Normalize consistently:

```python
def normalize_tag(tag: str) -> str:
    """Normalize to version with leading #, for internal use."""
    return f"#{tag.lstrip('#')}"

def frontmatter_tag(tag: str) -> str:
    """Normalize to version without leading #, for frontmatter storage."""
    return tag.lstrip("#")

def extract_tags(fm: dict) -> list[str]:
    raw = fm.get("tags", [])
    if isinstance(raw, str):
        raw = [raw]
    return [normalize_tag(t) for t in raw]
```

---

## 15. Patch Engine

The patch engine is the most performance-critical code path. It must handle UTF-8 + emoji correctly.

```python
def patch_note(
    vault_root: str,
    rel_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> PatchResult:
    abs_path = resolve(vault_root, rel_path)

    # Always work in bytes — handles emoji in paths and content
    content_bytes = abs_path.read_bytes()
    old_bytes = old_string.encode("utf-8")
    new_bytes = new_string.encode("utf-8")

    count = content_bytes.count(old_bytes)

    if count == 0:
        raise PatchNoMatchError(
            f"patch_note: old_string not found in {rel_path!r}. "
            f"The string may have changed since last read. Re-read and retry."
        )

    if count > 1 and not replace_all:
        raise PatchAmbiguousError(
            f"patch_note: old_string matches {count} times in {rel_path!r}. "
            f"Extend old_string with surrounding context to make it unique, "
            f"or set replace_all=True if all occurrences should be replaced."
        )

    if replace_all:
        result_bytes = content_bytes.replace(old_bytes, new_bytes)
        replacements = count
    else:
        result_bytes = content_bytes.replace(old_bytes, new_bytes, 1)
        replacements = 1

    atomic_write(abs_path, result_bytes)

    return PatchResult(
        path=rel_path,
        replacements=replacements,
        old_string_length=len(old_bytes),
        new_string_length=len(new_bytes),
    )
```

### Line-targeted patch (for task tools)

`complete_task` and `set_task_date` know the exact line number. Use a line-targeted variant to avoid ambiguity entirely:

```python
def patch_line(
    vault_root: str,
    rel_path: str,
    line: int,          # 1-indexed
    transform: Callable[[str], str],
) -> str:
    """
    Read file, apply transform() to the content of line `line`,
    write back atomically. Returns the new line content.
    Raises TaskStateError if the line doesn't exist.
    """
    abs_path = resolve(vault_root, rel_path)
    content = abs_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)

    if line < 1 or line > len(lines):
        raise TaskStateError(f"Line {line} out of range (file has {len(lines)} lines)")

    idx = line - 1
    original = lines[idx]
    transformed = transform(original)
    lines[idx] = transformed

    new_content = "".join(lines)
    atomic_write(abs_path, new_content.encode("utf-8"))
    return transformed.rstrip("\n")
```

---

## 16. Link-Aware Move

When a `.md` note is moved/renamed, all `[[wiki-links]]` that reference it by title must be updated across the vault.

### Link forms to handle

```
[[Note Title]]                   → plain link
[[Note Title|display text]]      → aliased link
[[Note Title#section]]           → section link
[[Note Title#section|display]]   → section + alias
```

The **title** in a wiki-link is the filename without the `.md` extension.

### Algorithm

```python
def move_note_with_link_rewrite(
    vault_root: str,
    source: str,
    destination: str,
) -> MoveNoteResult:
    vault = Path(vault_root)
    src_abs = resolve(vault_root, source)
    dst_abs = resolve(vault_root, destination)

    old_title = src_abs.stem  # filename without .md
    new_title = dst_abs.stem

    # Move the file first
    dst_abs.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_abs), str(dst_abs))

    if old_title == new_title:
        # Name didn't change (pure folder move), no links to update
        return MoveNoteResult(source=source, destination=destination,
                              links_rewritten=0, files_scanned=0)

    # Build regex to find all link forms referencing old_title
    # Escape the title for regex (may contain parens, dots, etc.)
    escaped = re.escape(old_title)
    link_re = re.compile(
        r'\[\[' + escaped + r'(\|[^\]]+|\#[^\]]+|\#[^\]]+\|[^\]]+)?\]\]'
    )

    def replace_link(m: re.Match) -> str:
        suffix = m.group(1) or ""
        return f"[[{new_title}{suffix}]]"

    files_scanned = 0
    links_rewritten = 0

    for md_file in vault.rglob("*.md"):
        files_scanned += 1
        content = md_file.read_text(encoding="utf-8", errors="replace")
        new_content, n = link_re.subn(replace_link, content)
        if n > 0:
            atomic_write(md_file, new_content.encode("utf-8"))
            links_rewritten += n

    return MoveNoteResult(
        source=source, destination=destination,
        links_rewritten=links_rewritten, files_scanned=files_scanned,
    )
```

**Performance note:** This is an O(vault size) operation. For a vault of a few thousand notes it completes in well under a second. No caching or index is needed.

---

## 17. Atomic Writes

All writes go through `atomic_write`. This prevents partial writes from corrupting notes if the process is killed mid-write.

```python
import tempfile
import os

def atomic_write(path: Path, content: bytes) -> None:
    """Write content to path atomically using a temp file + os.replace."""
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)

    # Write to a temp file in the same directory (ensures same filesystem)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp_path, path)  # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

---

## 18. Error Handling

### Exception hierarchy

```python
class VaultError(Exception):
    """Base for all vault-level errors."""

class VaultPathError(VaultError):
    """Path escapes vault root or is otherwise invalid."""

class NoteNotFoundError(VaultError):
    """The requested note path does not exist."""

class NotANoteError(VaultError):
    """The path exists but is not a .md file."""

class BatchTooLargeError(VaultError):
    """read_multiple_notes called with too many paths."""

class PatchNoMatchError(VaultError):
    """patch_note: old_string not found in file."""

class PatchAmbiguousError(VaultError):
    """patch_note: old_string matches multiple times and replace_all=False."""

class FrontmatterError(VaultError):
    """YAML parse or serialization error."""

class TaskStateError(VaultError):
    """Task is not in expected state (e.g., already completed)."""
```

### MCP error mapping

All `VaultError` subclasses are caught at the tool handler level and returned as MCP error responses (not Python exceptions — the MCP framework expects tool-level error returns):

```python
async def handle_tool(name: str, arguments: dict) -> ToolResult:
    try:
        result = await dispatch(name, arguments)
        return ToolResult(content=[TextContent(text=json.dumps(result))])
    except NoteNotFoundError as e:
        return ToolResult(isError=True, content=[TextContent(text=f"NOT_FOUND: {e}")])
    except PatchNoMatchError as e:
        return ToolResult(isError=True, content=[TextContent(text=f"PATCH_NO_MATCH: {e}")])
    except PatchAmbiguousError as e:
        return ToolResult(isError=True, content=[TextContent(text=f"PATCH_AMBIGUOUS: {e}")])
    except VaultPathError as e:
        return ToolResult(isError=True, content=[TextContent(text=f"INVALID_PATH: {e}")])
    except VaultError as e:
        return ToolResult(isError=True, content=[TextContent(text=f"VAULT_ERROR: {e}")])
    except Exception as e:
        logger.exception("Unexpected error in tool %s", name)
        return ToolResult(isError=True, content=[TextContent(text=f"INTERNAL_ERROR: {e}")])
```

---

## 19. Project Layout

```
obsidian-mcp/
├── pyproject.toml
├── Dockerfile
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── pvc.yaml
│
└── src/
    └── obsidian_mcp/
        ├── __init__.py
        ├── main.py             ← entry point; starts MCP server (stdio or Streamable HTTP)
        ├── config.py           ← Config (pydantic BaseSettings)
        ├── errors.py           ← exception hierarchy
        │
        ├── vault/
        │   ├── __init__.py
        │   ├── path.py         ← resolve(), to_relative(), path traversal guard
        │   ├── io.py           ← atomic_write(), read_note(), parse_note()
        │   ├── frontmatter.py  ← parse/serialize frontmatter (ruamel.yaml)
        │   ├── search.py       ← search_notes() + list_all_tags()
        │   └── links.py        ← move_note_with_link_rewrite()
        │
        ├── tasks/
        │   ├── __init__.py
        │   ├── parser.py       ← RawTask, parse_task_line(), collect_tasks_from_file()
        │   ├── collector.py    ← collect_all_tasks(), should_exclude_file()
        │   ├── sequencer.py    ← apply_project_sequencing(), is_project_note()
        │   ├── grouper.py      ← assign_group(), resolve_sort_date()
        │   └── mutator.py      ← complete_task(), set_task_date(), add_task()
        │
        └── tools/
            ├── __init__.py
            ├── registry.py     ← register all 19 tools with the MCP server
            ├── reading.py      ← read_note, read_multiple_notes, get_frontmatter,
            │                      get_notes_info, list_directory
            ├── searching.py    ← search_notes, list_all_tags
            ├── writing.py      ← write_note, patch_note, update_frontmatter, manage_tags
            ├── organizing.py   ← move_note, move_file, delete_note
            ├── vault_wide.py   ← get_vault_stats
            └── task_tools.py   ← get_tasks, complete_task, set_task_date, add_task
```

### Entry point

```python
# src/obsidian_mcp/main.py

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from .config import Config
from .tools.registry import register_all_tools

async def run_streamable_http(server: Server, config: Config):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route
    import uvicorn

    session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    async def health(_):
        return JSONResponse({"status": "ok"})

    @asynccontextmanager
    async def lifespan(_) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", endpoint=health),
            Mount("/mcp", app=session_manager.handle_request),
        ],
        lifespan=lifespan,
    )
    await uvicorn.Server(
        uvicorn.Config(app, host=config.mcp_host, port=config.mcp_port)
    ).serve()

async def main():
    config = Config()
    server = Server("obsidian-vault")
    register_all_tools(server, config)

    if config.mcp_transport == "stdio":
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    else:
        await run_streamable_http(server, config)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 20. Kubernetes Deployment

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[prod]"

COPY src/ src/

# Non-root user
RUN useradd -m -u 1000 mcp
USER mcp

ENV VAULT_PATH=/vault
ENV MCP_TRANSPORT=streamable-http
ENV MCP_PORT=8080

EXPOSE 8080

CMD ["python", "-m", "obsidian_mcp.main"]
```

Build for arm64:
```bash
docker buildx build --platform linux/arm64 -t your-registry/obsidian-mcp:latest .
```

### Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: obsidian-mcp
spec:
  replicas: 1       # RWO PVC — single replica
  selector:
    matchLabels:
      app: obsidian-mcp
  template:
    metadata:
      labels:
        app: obsidian-mcp
    spec:
      nodeSelector:
        kubernetes.io/arch: arm64
      containers:
      - name: obsidian-mcp
        image: your-registry/obsidian-mcp:latest
        ports:
        - containerPort: 8080
        env:
        - name: VAULT_PATH
          value: /vault
        - name: MCP_TRANSPORT
          value: streamable-http
        - name: LOG_LEVEL
          value: INFO
        # Optional: qmd sidecar for semantic search
        # - name: QMD_URL
        #   value: http://qmd:8181
        volumeMounts:
        - name: vault
          mountPath: /vault
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 2
          periodSeconds: 10
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: vault
        persistentVolumeClaim:
          claimName: obsidian-vault
---
apiVersion: v1
kind: Service
metadata:
  name: obsidian-mcp
spec:
  selector:
    app: obsidian-mcp
  ports:
  - port: 8080
    targetPort: 8080
```

### Vault sync (Obsidian headless sidecar)

The MCP server pod is stateless with respect to sync — it only reads/writes files. Vault population is handled by a separate pod or init container running headless Obsidian with Xvfb (for Obsidian Sync) or Syncthing:

```yaml
# Syncthing alternative (simpler, no Electron required)
- name: syncthing
  image: syncthing/syncthing:latest
  volumeMounts:
  - name: vault
    mountPath: /vault
  env:
  - name: STNODEFAULTFOLDER
    value: "true"
```

The vault PVC must be `ReadWriteMany` (NFS or equivalent) if both obsidian-sync and obsidian-mcp pods run concurrently on different nodes. If co-scheduled on the same node, `ReadWriteOnce` is sufficient.

---

## Appendix: Tool Name Summary

| # | Tool name | Category |
|---|---|---|
| 1 | `read_note` | Reading |
| 2 | `read_multiple_notes` | Reading |
| 3 | `get_frontmatter` | Reading |
| 4 | `get_notes_info` | Reading |
| 5 | `list_directory` | Reading |
| 6 | `search_notes` | Searching |
| 7 | `list_all_tags` | Searching |
| 8 | `write_note` | Writing |
| 9 | `patch_note` | Writing |
| 10 | `update_frontmatter` | Writing |
| 11 | `manage_tags` | Writing |
| 12 | `move_note` | Organizing |
| 13 | `move_file` | Organizing |
| 14 | `delete_note` | Organizing |
| 15 | `get_vault_stats` | Vault-wide |
| 16 | `get_tasks` | Tasks |
| 17 | `complete_task` | Tasks |
| 18 | `set_task_date` | Tasks |
| 19 | `add_task` | Tasks |

The `tool-mapping.md` in the obsidian skill references logical operation names. When this server is deployed, update that file to map each logical operation to the tool names above, and update the server name from `obsidian:*` to the new server identifier.

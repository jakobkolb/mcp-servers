# mcp-obsidian

Headless MCP server exposing **21 tools** for reading, writing, searching, and task management against a local Obsidian vault. No Obsidian process required — operates directly on the markdown filesystem.

**Transports:** Streamable HTTP on `:8080/mcp` (for k8s / Claude Web) · stdio (for Claude Desktop)

---

## Quick start

```bash
# Install
uv sync

# Run against a local vault (stdio mode, for Claude Desktop)
VAULT_PATH=/path/to/vault MCP_TRANSPORT=stdio python -m mcp_obsidian.main

# Run as HTTP server (for Claude Web / k8s)
VAULT_PATH=/path/to/vault python -m mcp_obsidian.main
```

### Claude Desktop config

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "python",
      "args": ["-m", "mcp_obsidian.main"],
      "env": {
        "VAULT_PATH": "/path/to/your/vault",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

---

## Configuration

All settings via environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `VAULT_PATH` | yes | — | Absolute path to vault root |
| `MCP_TRANSPORT` | no | `streamable-http` | `streamable-http` or `stdio` |
| `MCP_HOST` | no | `0.0.0.0` | Bind host (HTTP mode) |
| `MCP_PORT` | no | `8080` | Bind port (HTTP mode) |
| `QMD_URL` | no | — | qmd sidecar URL for semantic search |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING` |
| `SEARCH_LIMIT_MAX` | no | `20` | Hard ceiling on `search_notes` results |

---

## Tool reference

### Reading (4 tools)

#### `read_note`
Read a single markdown note. Returns frontmatter, body, raw content, and file metadata.

```
Input:  path (str, required)               vault-relative path, must end in .md
        pretty_print (bool, default false)
        include_content (bool, default true)      set false for frontmatter-only reads
        include_frontmatter (bool, default true)  set false for body-only reads
Output: path, frontmatter, content, raw, mtime, size
Errors: NOT_FOUND, NOT_A_NOTE, INVALID_PATH
```

#### `get_frontmatter`
Return only the YAML frontmatter of a note. ~5% the cost of `read_note`. Use for filter passes.

```
Input:  path (str, required)
Output: path, frontmatter
```

#### `get_notes_info`
Return filesystem metadata (mtime, ctime, size, is_note) without reading file content.

```
Input:  paths (list[str], required)
Output: notes (list with exists, mtime, ctime, size, is_note per entry)
```

#### `list_directory`
List files and subdirectories in a vault folder. Cheaper than `search_notes` when the path is known.

```
Input:  path (str, default "")     vault-relative folder; "" = vault root
        recursive (bool, default false)
Output: path, files, directories, total_files, total_dirs
```

---

### Searching (2 tools)

#### `search_notes`
Full-text regex search across vault `.md` files. Falls back to literal match when query is not valid regex.

When `QMD_URL` is set, `search_notes` will delegate to the [qmd](https://github.com/tobi/qmd) sidecar for semantic / lexical search — see [qmd sidecar](#qmd-sidecar-semantic-search) below. **Not yet implemented** — the config field exists but delegation is not wired up yet.

```
Input:  query (str, required)
        search_content (bool, default true)
        search_frontmatter (bool, default false)
        case_sensitive (bool, default false)
        limit (int, default 5, capped at SEARCH_LIMIT_MAX)
        path_filter (str, optional)              restrict to notes under this folder prefix
        include_frontmatter (bool, default false) include parsed frontmatter in each result
        tag_filter (str, optional)               return only notes that have this tag
                                                 (frontmatter tags: or inline #tag)
        frontmatter_filter (object, optional)    return only notes where all specified
                                                 frontmatter fields match (exact match)
Output: results (list with path, snippet, score, line, frontmatter_match)
        total_found, query, search_mode
```

#### `list_all_tags`
Return all vault tags with occurrence counts, sorted by count descending. Covers both frontmatter `tags:` and inline `#hashtags`.

```
Input:  (none)
Output: tags (list with tag, count, sources), total_unique
```

---

### Writing (4 tools)

#### `write_note`
Create or write a note. All writes are atomic.

```
Input:  path (str, required)
        content (str, required)
        mode (str, default "overwrite")    "overwrite" | "append" | "prepend" | "create"
        create_dirs (bool, default true)
Output: path, mode, bytes_written, created
Errors: ALREADY_EXISTS (mode=create and note already exists)
```

`create` mode fails with `ALREADY_EXISTS` if the note already exists, making it safe for initialising notes without clobbering existing content.

#### `patch_note`
Targeted find-and-replace within a note. Works on raw bytes to handle emoji correctly.

```
Input:  path (str, required)
        old_string (str, required)    must match exactly (including whitespace)
        new_string (str, required)
        replace_all (bool, default false)
Output: path, replacements, old_string_length, new_string_length
Errors: PATCH_NO_MATCH, PATCH_AMBIGUOUS
```

#### `update_frontmatter`
Merge or replace frontmatter fields on a note, preserving the body. Serializes with `ruamel.yaml` (no date quoting, proper booleans).

```
Input:  path (str, required)
        frontmatter (object, required)    fields to set/update
        merge (bool, default true)        false = replace entire frontmatter
Output: path, fields_updated, fields_added, frontmatter_after
```

#### `manage_tags`
Add, remove, or list tags in the frontmatter `tags:` field. For inline `#tags` in the body, use `patch_note`.

```
Input:  path (str, required)
        operation (str, required)    "add" | "remove" | "list"
        tags (list[str], default [])
Output: path, operation, tags_before, tags_after, tags_added, tags_removed
```

---

### Organizing (5 tools)

#### `move_note`
Move or rename a `.md` note, rewriting `[[wiki-links]]` that reference it across the vault.

```
Input:  source (str, required)
        destination (str, required)
        create_dirs (bool, default true)
Output: source, destination, links_rewritten, files_scanned
```

#### `move_file`
Move any file without rewriting wiki-links. Binary-safe. Use `move_note` for `.md` files unless link rewriting is unwanted.

```
Input:  source (str, required)
        destination (str, required)
        create_dirs (bool, default true)
Output: source, destination
```

#### `delete_note`
Delete a markdown note. Irreversible. Requires `confirm=true` to proceed.

```
Input:  path (str, required)
        confirm (bool, default false)    must be true to actually delete
Output: path, deleted, message
Errors: NOT_FOUND
```

#### `get_backlinks`
Return all notes that contain a `[[wiki-link]]` pointing to the given note. Useful for knowledge graph navigation.

```
Input:  path (str, required)    vault-relative path of the note to find backlinks for
Output: path, backlinks (list with source_path, line, context), total
```

#### `get_outgoing_links`
Return all `[[wiki-links]]` found in a note body, with line number, context snippet, and an `exists` flag (false means a broken link).

```
Input:  path (str, required)    vault-relative path of the note to inspect
Output: path, links (list with target, line, context, exists), total
```

---

### Vault-wide (1 tool)

#### `get_vault_stats`
Return vault stats: note/file/dir counts, total size, recently modified.

```
Input:  (none)
Output: total_notes, total_files, total_dirs, total_size_bytes,
        recently_modified (top 10 by mtime), vault_path, generated_at
```

---

### Tasks (4 tools)

These tools implement GTD task management on top of the vault's markdown format. They understand the [Obsidian Tasks](https://github.com/obsidian-tasks-group/obsidian-tasks) plugin emoji syntax and the project sequencing convention.

#### `get_tasks`
Collect all open tasks from the vault. Applies project sequencing (first task per section), excludes the Utility folder, and groups tasks by priority/waiting/normal/notag/someday.

```
Input:  context_tag (str, optional)          filter to tasks with this tag, e.g. "#context/pc"
        group (str, optional)                "priority"|"waiting"|"normal"|"notag"|"someday"
        path (str, optional)                 restrict to tasks in this note or folder prefix
        hide_future_scheduled (bool, default true)
        include_someday (bool, default false)
        include_waiting (bool, default true)
        project_tasks_only (bool, default false)
        exclude_projects (bool, default false)
        apply_sequencing (bool, default true)    GTD sequencing on #project notes (first task per section)

Output: tasks (flat list), projects_without_next_action, total_tasks, generated_at

Task fields: path, line, raw_line, text, tags, due_date, scheduled_date,
             start_date, created_date, priority, recurrence, group,
             sort_date_ms, project_name, project_path, project_section, is_sequenced
```

**Task emoji spec:**

| Emoji | Meaning |
|---|---|
| 📅 | Due date |
| ⏳ | Scheduled date |
| 🛫 | Start date |
| ➕ | Created date |
| ✅ | Done date |
| 🔁 | Recurrence |
| 🔺 ⏫ 🔼 🔽 ⏬ | Priority (highest→lowest) |

#### `complete_task`
Mark an open task as done. Patches `- [ ]` → `- [x]` and appends `✅ YYYY-MM-DD`.

```
Input:  path (str, required)
        line (int, required)           1-indexed line number from get_tasks result
        done_date (str, optional)      YYYY-MM-DD; defaults to today
Output: path, line, task_text, done_date, patched
Errors: TASK_STATE_ERROR (line is not an open task), VAULT_ERROR
```

#### `set_task_date`
Set, update, or remove a date emoji field (⏳ 📅 🛫 ➕) on a task line.

```
Input:  path (str, required)
        line (int, required)
        date_type (str, required)      "due" | "scheduled" | "start" | "created"
        date (str, optional)           YYYY-MM-DD; null removes the field
Output: path, line, date_type, date_before, date_after, patched
```

#### `add_task`
Append a new task to a file with proper emoji metadata formatting.

```
Input:  path (str, required)
        text (str, required)           task description (no emoji needed)
        tags (list[str], default [])
        scheduled_date (str, optional)
        due_date (str, optional)
        start_date (str, optional)
        priority (str, default "")     "highest"|"high"|"medium"|"low"|"lowest"|""
        stamp_created (bool, default true)
        append_under_heading (str, optional)    insert after last task under this heading
Output: path, task_line, line, created
```

---

### Batch (1 tool)

#### `batch_tool`
Execute multiple tool calls in a single request. Read-only tools run fully in parallel; write tools are serialised per-path to prevent races. All invocations are schema-validated before any are executed.

```
Input:  invocations (list, required)
          Each item: { tool (str), arguments (object) }
Output: status ("ok" | "validation_failed")
        results (list with index, tool, result, error per invocation)
        errors  (list of {index, tool, error}, only present on validation_failed)
```

Useful for bulk reads (fetch 20 notes in one round-trip) or multi-step workflows where writes to different paths can be parallelised.

---

## Error codes

| Code | Meaning |
|---|---|
| `NOT_FOUND` | Note path does not exist |
| `NOT_A_NOTE` | Path exists but is not a `.md` file |
| `INVALID_PATH` | Path traversal attempt or invalid path |
| `ALREADY_EXISTS` | `write_note` with `mode=create` but the note already exists |
| `PATCH_NO_MATCH` | `old_string` not found in file |
| `PATCH_AMBIGUOUS` | `old_string` matches multiple times; use `replace_all=true` |
| `TASK_STATE_ERROR` | Line is not an open task (stale line number) |
| `VAULT_ERROR` | Other vault-level error |
| `INTERNAL_ERROR` | Unexpected server error |

---

## Vault conventions (GTD)

The task engine is configured for a GTD-style vault with these defaults:

**Excluded from task collection:**
- Folder: `Utility/`
- Page tags: `#exclude-master-tasklist`, `#completed`
- Section headings: `Morgens - 2 Minuten Check In`, `Abends - 10 Minuten Cleanup`

**Project sequencing:** Notes tagged `project` in frontmatter get GTD sequencing applied — only the first open task per section heading is surfaced. Sections containing `🟰` bypass sequencing (parallel tasks). Sections containing "exclude" are skipped.

**Context tags used in the vault:**
`#context/pc`, `#context/work`, `#context/kids`, `#context/phone`, `#context/home`, `#context/errands`, `#context/reading`, `#context/watchlist`

---

## qmd sidecar (semantic search)

[qmd](https://github.com/tobi/qmd) is a lightweight local search server that builds a vector index over a markdown directory and exposes it as an MCP server. Running it alongside mcp-obsidian enables semantic / full-text lexical search in addition to the built-in regex search.

> **Status:** The `QMD_URL` config field is wired up but `search_notes` does not yet delegate to qmd. When the delegation is implemented, it will be documented here.

### How it will work

When `QMD_URL` is set, `search_notes` will try qmd first and fall back to regex on failure:

1. **qmd** — POST the query to qmd's MCP endpoint. Returns semantically ranked results with snippets.
2. **Regex fallback** — Always available. Walks all `.md` files, applies `re.search`. Score is `1.0` for case-sensitive, `0.5` for case-insensitive match.

The `search_mode` field in the `search_notes` response will reflect which backend was used (`"regex"` or `"qmd_semantic"`).

### Running qmd locally

```bash
# Install qmd (requires Go)
go install github.com/tobi/qmd@latest

# Start qmd pointing at your vault
qmd serve --dir /path/to/vault --port 8181
```

Then set `QMD_URL=http://localhost:8181` when starting mcp-obsidian.

### Kubernetes deployment

Add qmd as a sidecar container in the same pod as mcp-obsidian so it shares the vault PVC:

```yaml
# In chart/values/mcp-obsidian.yaml — add to extraEnv and sidecars
extraEnv:
  - name: QMD_URL
    value: http://localhost:8181

# Add to the deployment as a sidecar (via extraContainers if supported,
# or by extending the Helm chart values):
sidecars:
  - name: qmd
    image: ghcr.io/tobi/qmd:latest
    args: ["serve", "--dir", "/vault", "--port", "8181"]
    ports:
      - containerPort: 8181
    volumeMounts:
      - name: vault
        mountPath: /vault
        readOnly: true
```

Since both containers are in the same pod they share the vault PVC without needing `ReadWriteMany` — qmd gets a read-only view, mcp-obsidian keeps read-write access.

---

## Development

```bash
# Run all tests
make test SERVER=mcp-obsidian

# Watch mode (re-runs on file changes)
make test-watch SERVER=mcp-obsidian

# Lint
make lint
```

Test layout:
- `tests/unit/` — unit tests (vault I/O, task parser, task mutator, search, sequencing, links, batch)
- `tests/integration/` — integration tests against a live MCP server subprocess
  - `test_read_note_integration.py` — read tool coverage
  - `test_vault_tools_integration.py` — multi-step workflows (tag rename, complete, defer, search, add, project sequencing)

---

## Deployment (Kubernetes)

The server is deployed via the shared Helm chart at [`chart/mcp-server`](../../chart/mcp-server).
Values for this server are in [`chart/values/mcp-obsidian.yaml`](../../chart/values/mcp-obsidian.yaml).

The vault PVC (`obsidian-vault`) is populated by a headless Obsidian sidecar running Obsidian Sync. A second PVC (`obsidian-headless-state`) holds Obsidian's app state.

```bash
# Deploy
helm upgrade --install mcp-obsidian chart/mcp-server -f chart/values/mcp-obsidian.yaml
```

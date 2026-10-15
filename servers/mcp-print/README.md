# mcp-print

Print over MCP through the CUPS server on the Kubernetes host. The agent passes the
**document itself** in the tool call (HTML, Markdown or plain text); a Chromium sidecar
([Gotenberg](https://gotenberg.dev)) renders it to PDF and `lp` queues it.

- **Inline only.** No tool takes a path, URL or file reference, and unknown arguments are
  rejected before anything runs. A test fails the build if a tool grows such an argument.
- **Renderer without network.** Gotenberg listens on the pod's loopback only, denies every
  URL except its own temp files, resolves no host names and runs no JavaScript. Images must
  be embedded as `data:` URIs; anything else is dropped.
- **Limits.** Documents over `PRINT_MAX_PAGES` are refused before anything is queued;
  `copies` is capped at `PRINT_MAX_COPIES`. `PRINT_ALLOWED_PRINTERS` restricts the queues.

## Tools

| Tool | Description |
|------|-------------|
| `list_printers` | Allowed CUPS queues: state (`idle`, `printing`, `disabled` + reason), accepting jobs, default |
| `preview_document` | Render without printing: page count and a PNG of the first page |
| `print_document` | Render and print. `content`, `format` (`html`/`markdown`/`text`), `printer`, `copies`, `duplex`, `paper` (A4, A5, Letter, Legal), `landscape`, `title` |
| `list_jobs` | Queued/printing jobs, or finished ones with `completed=true` |
| `cancel_job` | Cancel a job by id (`<printer>-<n>`) |

## Setup

1. **CUPS on the host** with at least one queue (`lpstat -p` lists it). Nothing has to listen
   on the network: the pod mounts the host's `/run/cups` and talks to `cups.sock`.
2. Deploy with the example values (`chart/values/mcp-print.yaml`): the MCP server plus the
   `renderer` sidecar, and the `/run/cups` hostPath mount.
3. Ask the agent to `list_printers`, then set `PRINT_DEFAULT_PRINTER` (or a CUPS default with
   `lpadmin -d`) and, if you like, `PRINT_ALLOWED_PRINTERS`.

To use a remote CUPS instead, set `CUPS_SERVER=host:631` and drop the hostPath mount; that
CUPS then has to accept connections from the pod network.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CUPS_SERVER` | `/run/cups/cups.sock` | CUPS socket path or `host:port` (read by `lp`/`lpstat`) |
| `PRINT_RENDERER_URL` | `http://127.0.0.1:3000` | Gotenberg sidecar |
| `PRINT_ALLOWED_PRINTERS` | *(empty)* | Comma-separated queue names; empty allows all |
| `PRINT_DEFAULT_PRINTER` | *(empty)* | Queue used when `printer` is omitted; empty uses the CUPS default |
| `PRINT_MAX_PAGES` | `20` | Longer documents are not printed |
| `PRINT_MAX_COPIES` | `10` | Upper bound for `copies` |
| `PRINT_MAX_CONTENT_BYTES` | `2000000` | Upper bound for `content` |
| `PORT` | `8000` | MCP HTTP port |

## Tests

```bash
make test SERVER=mcp-print
```

| Layer | What it proves |
|-------|----------------|
| cups | parsing of real CUPS 2.4 `lpstat`/`lp` output (fake binaries replay it), C locale, PDF on stdin, option injection via printer names and job ids rejected |
| render | Markdown/text to HTML (escaped), paper sizes, the Gotenberg requests |
| tools | no path/URL/file arguments, strict schemas, allowlist on every tool, page and size limits, preview prints nothing |
| server | MCP over HTTP end to end, image content, failures as tool errors |

Verified by hand against a real `cupsd` and the locked-down Gotenberg sidecar: the queued job
is a valid PDF, and external URLs in the document are never requested (the same document
with Gotenberg's default flags fetches all of them and runs its script).

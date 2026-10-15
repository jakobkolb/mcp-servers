"""Tool table and dispatch.

The document to print is always the `content` argument itself. No tool takes a path,
a URL or a file reference, so nothing can be printed that did not arrive in the call.
"""

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jsonschema
from mcp.types import ImageContent, TextContent, Tool

from .config import Config
from .cups import SIDES, Cups, check_printer_name, job_printer
from .render import FORMATS, PAPER, Layout, Renderer, page_count, to_html

Content = TextContent | ImageContent

_S: dict[str, Any] = {"type": "string"}
_CONTENT_NOTE = (
    " The renderer has no network access and runs no JavaScript: put CSS inline and embed"
    " images as data: URIs."
)


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


def _json(value: Any) -> list[Content]:
    return [TextContent(type="text", text=json.dumps(value))]


@dataclass(frozen=True)
class _Tool:
    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[..., list[Content]]


class PrintTools:
    def __init__(self, config: Config, renderer: Renderer, cups: Cups) -> None:
        self._config = config
        self._renderer = renderer
        self._cups = cups
        document = {
            "content": {
                "type": "string",
                "minLength": 1,
                "description": "The complete document itself (not a path or URL).",
            },
            "format": {
                "enum": list(FORMATS),
                "description": "How to read `content`. Default html.",
            },
            "paper": {"enum": list(PAPER), "description": "Default A4."},
            "landscape": {"type": "boolean"},
        }
        self._tools = [
            _Tool(
                "list_printers",
                "List the printers this server may print to: name, state (idle, printing,"
                " disabled), whether they accept jobs, and which one is used by default.",
                _schema({}),
                lambda: _json(self._printers()),
            ),
            _Tool(
                "preview_document",
                "Render a document without printing it. Returns the page count and a picture of"
                " the first page, to check the layout before calling print_document."
                + _CONTENT_NOTE,
                _schema(document, ["content"]),
                self._preview,
            ),
            _Tool(
                "print_document",
                "Print a document. Pass the whole document in `content`: HTML (a full page with"
                " inline CSS), Markdown or plain text. Files, paths and URLs cannot be printed."
                + _CONTENT_NOTE
                + f" At most {config.max_pages} pages per document. Returns the job id.",
                _schema(
                    {
                        **document,
                        "printer": {
                            **_S,
                            "description": "Printer name from list_printers. Default: the"
                            " default printer.",
                        },
                        "copies": {"type": "integer", "minimum": 1, "maximum": config.max_copies},
                        "duplex": {"enum": list(SIDES), "description": "Default: the printer's."},
                        "title": {**_S, "maxLength": 200, "description": "Job name in the queue."},
                    },
                    ["content"],
                ),
                self._print,
            ),
            _Tool(
                "list_jobs",
                "List print jobs: queued and printing ones by default, or finished ones with"
                " completed=true. Optionally for one printer.",
                _schema({"printer": _S, "completed": {"type": "boolean"}}),
                self._jobs,
            ),
            _Tool(
                "cancel_job",
                "Cancel a queued or printing job by its job id (from print_document or list_jobs).",
                _schema({"job_id": _S}, ["job_id"]),
                self._cancel,
            ),
        ]
        self._by_name = {t.name: t for t in self._tools}

    # -- printers -------------------------------------------------------------

    def _allowed(self, printer: str) -> bool:
        allowed = self._config.allowed_printers
        return not allowed or printer in allowed

    def _printers(self) -> dict[str, Any]:
        printers = [p for p in self._cups.printers() if self._allowed(p["name"])]
        default = self._default()
        for p in printers:
            p["default"] = p["name"] == default
        return {"printers": printers, "default": default or None}

    def _default(self) -> str:
        name = self._config.default_printer or self._cups.default_printer()
        return name if name and self._allowed(name) else ""

    def _printer(self, name: str | None) -> str:
        if not name:
            name = self._default()
            if not name:
                raise ValueError("No printer given and no default printer; call list_printers")
        check_printer_name(name)
        if not self._allowed(name):
            raise ValueError(f"Printer not available: {name}")
        return name

    # -- documents ------------------------------------------------------------

    def _render(
        self, content: str, format: str, paper: str, landscape: bool, title: str = ""
    ) -> tuple[str, Layout, bytes, int]:
        size = len(content.encode())
        if size > self._config.max_content_bytes:
            raise ValueError(
                f"Document too large: {size} bytes (limit {self._config.max_content_bytes})"
            )
        doc = to_html(content, format, title)
        layout = Layout(paper, landscape)
        pdf = self._renderer.pdf(doc, layout)
        return doc, layout, pdf, page_count(pdf)

    def _preview(
        self, content: str, format: str = "html", paper: str = "A4", landscape: bool = False
    ) -> list[Content]:
        doc, layout, _, pages = self._render(content, format, paper, landscape)
        png = self._renderer.screenshot(doc, layout)
        info = {"pages": pages, "max_pages": self._config.max_pages, "paper": paper}
        return [
            *_json(info),
            ImageContent(type="image", data=base64.b64encode(png).decode(), mime_type="image/png"),
        ]

    def _print(
        self,
        content: str,
        format: str = "html",
        paper: str = "A4",
        landscape: bool = False,
        printer: str | None = None,
        copies: int = 1,
        duplex: str | None = None,
        title: str = "",
    ) -> list[Content]:
        target = self._printer(printer)
        _, _, pdf, pages = self._render(content, format, paper, landscape, title)
        if pages > self._config.max_pages:
            raise ValueError(
                f"Document has {pages} pages, more than the limit of {self._config.max_pages};"
                " nothing was printed"
            )
        job = self._cups.submit(
            pdf, target, copies=copies, title=title or "mcp-print", sides=duplex, media=paper
        )
        return _json({"job_id": job, "printer": target, "pages": pages, "copies": copies})

    # -- jobs -----------------------------------------------------------------

    def _jobs(self, printer: str | None = None, completed: bool = False) -> list[Content]:
        if printer:
            self._printer(printer)
        jobs = [
            j for j in self._cups.jobs(printer, completed=completed) if self._allowed(j["printer"])
        ]
        return _json(jobs)

    def _cancel(self, job_id: str) -> list[Content]:
        if not self._allowed(job_printer(job_id)):
            raise ValueError(f"Printer not available: {job_printer(job_id)}")
        self._cups.cancel(job_id)
        return _json({"cancelled": job_id})

    # -- dispatch -------------------------------------------------------------

    def list_tools(self) -> list[Tool]:
        return [
            Tool(name=t.name, description=t.description, input_schema=t.schema) for t in self._tools
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> list[Content]:
        tool = self._by_name.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        try:
            jsonschema.validate(arguments, tool.schema)
        except jsonschema.ValidationError as e:
            raise ValueError(f"Invalid arguments for {name}: {e.message}") from None
        return tool.run(**arguments)

"""Turns inline content into a PDF through the Gotenberg (Chromium) sidecar.

The content only ever arrives as a string from the tool call. The sidecar is started
with outbound requests and JavaScript disabled (see chart/values/mcp-print.yaml), so
the document cannot pull anything in from the network either.
"""

import html
import io
from dataclasses import dataclass

import httpx
import markdown
from pypdf import PdfReader

FORMATS = ("html", "markdown", "text")
# Width x height in inches, portrait.
PAPER = {"A4": (8.27, 11.69), "A5": (5.83, 8.27), "Letter": (8.5, 11.0), "Legal": (8.5, 14.0)}
_MARGIN_IN = "0.6"
_CSS_PX_PER_IN = 96

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title><style>
body {{ font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif; font-size: 11pt;
       line-height: 1.4; color: #000; }}
h1, h2, h3 {{ line-height: 1.2; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid #888; padding: 4px 8px; text-align: left; }}
pre, code {{ font-family: "DejaVu Sans Mono", "Liberation Mono", monospace; font-size: 10pt; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
</style></head><body>
{body}
</body></html>
"""


def to_html(content: str, fmt: str, title: str = "") -> str:
    """The document as HTML. HTML input is used as is."""
    if fmt == "html":
        return content
    if fmt == "markdown":
        body = markdown.markdown(content, extensions=["tables", "fenced_code", "sane_lists"])
    elif fmt == "text":
        body = f"<pre>{html.escape(content)}</pre>"
    else:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}")
    return _PAGE.format(title=html.escape(title), body=body)


def page_count(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


@dataclass(frozen=True)
class Layout:
    paper: str = "A4"
    landscape: bool = False

    def portrait_in(self) -> tuple[float, float]:
        if self.paper not in PAPER:
            raise ValueError(f"paper must be one of {', '.join(PAPER)}")
        return PAPER[self.paper]

    def size_in(self) -> tuple[float, float]:
        w, h = self.portrait_in()
        return (h, w) if self.landscape else (w, h)


class Renderer:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def _post(self, route: str, doc: str, fields: dict[str, str]) -> bytes:
        files = {"files": ("index.html", doc.encode(), "text/html")}
        try:
            r = self._http.post(route, files=files, data=fields)
        except httpx.HTTPError as e:
            raise RuntimeError(f"Renderer unreachable: {e}") from e
        if r.status_code != 200:
            raise RuntimeError(f"Renderer returned HTTP {r.status_code}: {r.text[:200]}")
        return r.content

    def pdf(self, doc: str, layout: Layout) -> bytes:
        w, h = layout.portrait_in()  # Chromium applies `landscape` itself
        return self._post(
            "/forms/chromium/convert/html",
            doc,
            {
                "paperWidth": str(w),
                "paperHeight": str(h),
                "landscape": str(layout.landscape).lower(),
                "printBackground": "true",
                **{f"margin{side}": _MARGIN_IN for side in ("Top", "Bottom", "Left", "Right")},
            },
        )

    def screenshot(self, doc: str, layout: Layout) -> bytes:
        """PNG of roughly the first page, rendered with print styles."""
        w, h = layout.size_in()
        return self._post(
            "/forms/chromium/screenshot/html",
            doc,
            {
                "width": str(round(w * _CSS_PX_PER_IN)),
                "height": str(round(h * _CSS_PX_PER_IN)),
                "clip": "true",
                "format": "png",
                "emulatedMediaType": "print",
            },
        )

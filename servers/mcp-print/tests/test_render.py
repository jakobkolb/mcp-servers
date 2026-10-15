import httpx
import pytest
from mcp_print.render import Layout, Renderer, page_count, to_html


def test_html_is_passed_through_untouched():
    doc = "<html><body><p style='color:red'>x</p></body></html>"
    assert to_html(doc, "html") == doc


def test_markdown_becomes_a_full_page_with_tables():
    out = to_html("# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |", "markdown", title="T")
    assert out.startswith("<!doctype html>")
    assert "<h1>Title</h1>" in out and "<table>" in out
    assert '<meta charset="utf-8">' in out and "<title>T</title>" in out


def test_text_is_escaped_and_keeps_its_line_breaks():
    out = to_html("a < b\n<script>x</script>\n  indented", "text")
    assert "<pre>a &lt; b\n&lt;script&gt;x&lt;/script&gt;\n  indented</pre>" in out
    assert "<script>" not in out


def test_title_is_escaped():
    assert "<title>&lt;b&gt;</title>" in to_html("x", "text", title="<b>")


def test_unknown_format():
    with pytest.raises(ValueError, match="format"):
        to_html("x", "pdf")


def test_page_count(pdf_of):
    assert page_count(pdf_of(3)) == 3


@pytest.mark.parametrize(
    ("layout", "size"),
    [
        (Layout(), (8.27, 11.69)),
        (Layout("Letter", landscape=True), (11.0, 8.5)),
    ],
)
def test_layout_size(layout, size):
    assert layout.size_in() == size


def test_unknown_paper():
    with pytest.raises(ValueError, match="paper"):
        Layout("A3").size_in()


def test_pdf_request(renderer):
    pdf = Renderer(renderer.client()).pdf("<p>hi</p>", Layout("A4", landscape=True))
    assert page_count(pdf) == 2
    [(route, fields, doc)] = renderer.requests
    assert route == "/forms/chromium/convert/html"
    assert doc == "<p>hi</p>"
    # Chromium rotates portrait paper itself when landscape is set.
    assert fields["paperWidth"] == "8.27" and fields["paperHeight"] == "11.69"
    assert fields["landscape"] == "true"


def test_screenshot_request(renderer, png):
    assert Renderer(renderer.client()).screenshot("<p>hi</p>", Layout("A4")) == png
    [(route, fields, _)] = renderer.requests
    assert route == "/forms/chromium/screenshot/html"
    assert (fields["width"], fields["height"]) == ("794", "1122")
    assert fields["emulatedMediaType"] == "print"


def test_renderer_errors(renderer):
    renderer.http_status = 503
    with pytest.raises(RuntimeError, match="HTTP 503"):
        Renderer(renderer.client()).pdf("x", Layout())
    renderer.http_status = None
    renderer.fail = httpx.ConnectError("refused")
    with pytest.raises(RuntimeError, match="unreachable"):
        Renderer(renderer.client()).pdf("x", Layout())

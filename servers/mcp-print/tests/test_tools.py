import base64
import json
from dataclasses import replace

import pytest
from mcp_print.render import Renderer
from mcp_print.tools import PrintTools


@pytest.fixture
def tools(config, renderer, fake_cups):
    def make(**overrides):
        return PrintTools(
            replace(config, **overrides), Renderer(renderer.client()), fake_cups.cups()
        )

    return make


def call(t, name, **args):
    content = t.call(name, args)
    return json.loads(content[0].text)


def lp_calls(fake_cups):
    return [c for c in fake_cups.calls if c["cmd"] == "lp"]


def test_exposes_exactly_these_tools(tools):
    assert {t.name for t in tools().list_tools()} == {
        "list_printers",
        "preview_document",
        "print_document",
        "list_jobs",
        "cancel_job",
    }


def test_every_tool_declares_a_strict_schema(tools):
    for t in tools().list_tools():
        assert t.input_schema["type"] == "object"
        assert t.input_schema["additionalProperties"] is False, t.name
        assert t.description and len(t.description) > 20


def test_no_tool_accepts_a_path_url_or_file(tools):
    """The document can only arrive inline: no argument can point somewhere else."""
    forbidden = ("path", "url", "uri", "file", "src", "href", "location")
    for t in tools().list_tools():
        for prop in t.input_schema["properties"]:
            assert not any(word in prop.lower() for word in forbidden), (t.name, prop)


@pytest.mark.parametrize("arg", ["path", "url", "file", "file_path"])
def test_extra_arguments_are_refused_before_anything_runs(tools, renderer, fake_cups, arg):
    with pytest.raises(ValueError, match="Invalid arguments"):
        tools().call("print_document", {"content": "x", arg: "/etc/passwd"})
    assert renderer.requests == [] and fake_cups.calls == []


def test_list_printers_marks_the_default(tools):
    out = call(tools(), "list_printers")
    assert out["default"] == "Office-Laser"
    assert [(p["name"], p["default"]) for p in out["printers"]] == [
        ("Office-Laser", True),
        ("Kitchen", False),
        ("Old", False),
    ]


def test_allowlist_hides_other_printers(tools):
    out = call(tools(allowed_printers=frozenset({"Kitchen"})), "list_printers")
    assert [p["name"] for p in out["printers"]] == ["Kitchen"]
    assert out["default"] is None  # the CUPS default is not allowed


def test_print_renders_inline_content_and_queues_it(tools, renderer, fake_cups):
    out = call(
        tools(),
        "print_document",
        content="# Einkaufsliste\n\n- Milch",
        format="markdown",
        copies=2,
        duplex="two-sided-long-edge",
        title="Liste",
    )
    assert out == {"job_id": "Office-Laser-7", "printer": "Office-Laser", "pages": 2, "copies": 2}
    [(route, _, doc)] = renderer.requests
    assert route == "/forms/chromium/convert/html" and "<h1>Einkaufsliste</h1>" in doc
    [lp] = lp_calls(fake_cups)
    assert lp["args"][:4] == ["-d", "Office-Laser", "-n", "2"]
    assert "sides=two-sided-long-edge" in lp["args"] and "media=A4" in lp["args"]
    assert lp["stdin"].startswith("%PDF")


def test_print_uses_the_configured_default_over_the_cups_one(tools, fake_cups):
    out = call(tools(default_printer="Kitchen"), "print_document", content="x", format="text")
    assert out["printer"] == "Kitchen"


def test_print_without_any_default_asks_for_a_printer(tools, fake_cups):
    fake_cups.state["default"] = None
    with pytest.raises(ValueError, match="list_printers"):
        tools().call("print_document", {"content": "x"})


def test_print_to_a_printer_outside_the_allowlist_is_refused(tools, renderer, fake_cups):
    t = tools(allowed_printers=frozenset({"Kitchen"}))
    with pytest.raises(ValueError, match="not available"):
        t.call("print_document", {"content": "x", "printer": "Office-Laser"})
    assert renderer.requests == [] and lp_calls(fake_cups) == []


def test_documents_over_the_page_limit_are_not_printed(tools, renderer, fake_cups):
    renderer.pages = 21
    with pytest.raises(ValueError, match="21 pages.*nothing was printed"):
        tools(max_pages=20).call("print_document", {"content": "x"})
    assert lp_calls(fake_cups) == []


def test_oversized_content_is_refused_before_rendering(tools, renderer):
    with pytest.raises(ValueError, match="too large"):
        tools(max_content_bytes=10).call("print_document", {"content": "ü" * 6})
    assert renderer.requests == []


@pytest.mark.parametrize(
    "args",
    [
        {"content": ""},
        {"content": "x", "copies": 0},
        {"content": "x", "copies": 11},
        {"content": "x", "format": "pdf"},
        {"content": "x", "paper": "A3"},
        {"content": "x", "duplex": "both"},
        {},
    ],
)
def test_invalid_print_arguments(tools, fake_cups, args):
    with pytest.raises(ValueError, match="Invalid arguments"):
        tools().call("print_document", args)
    assert lp_calls(fake_cups) == []


def test_copies_limit_follows_config(tools):
    schema = next(t for t in tools(max_copies=3).list_tools() if t.name == "print_document")
    assert schema.input_schema["properties"]["copies"]["maximum"] == 3


def test_preview_returns_page_count_and_an_image_and_prints_nothing(
    tools, renderer, fake_cups, png
):
    renderer.pages = 3
    info, image = tools().call(
        "preview_document", {"content": "x", "format": "text", "landscape": True}
    )
    assert json.loads(info.text) == {"pages": 3, "max_pages": 20, "paper": "A4"}
    assert image.mime_type == "image/png" and base64.b64decode(image.data) == png
    assert [r[0] for r in renderer.requests] == [
        "/forms/chromium/convert/html",
        "/forms/chromium/screenshot/html",
    ]
    assert lp_calls(fake_cups) == []


def test_list_jobs_respects_the_allowlist(tools):
    assert [j["job_id"] for j in call(tools(), "list_jobs")] == ["Office-Laser-3", "Kitchen-4"]
    only_kitchen = tools(allowed_printers=frozenset({"Kitchen"}))
    assert [j["job_id"] for j in call(only_kitchen, "list_jobs")] == ["Kitchen-4"]
    with pytest.raises(ValueError, match="not available"):
        only_kitchen.call("list_jobs", {"printer": "Office-Laser"})


def test_cancel_job(tools, fake_cups):
    assert call(tools(), "cancel_job", job_id="Kitchen-4") == {"cancelled": "Kitchen-4"}
    with pytest.raises(ValueError, match="not available"):
        tools(allowed_printers=frozenset({"Kitchen"})).call(
            "cancel_job", {"job_id": "Office-Laser-3"}
        )
    assert [c["args"] for c in fake_cups.calls if c["cmd"] == "cancel"] == [["Kitchen-4"]]


def test_unknown_tool(tools):
    with pytest.raises(ValueError, match="Unknown tool"):
        tools().call("print_file", {})

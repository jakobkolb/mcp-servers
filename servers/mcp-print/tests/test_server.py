import json

import httpx
import pytest
from mcp_print.server import build_app
from starlette.testclient import TestClient

HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


def rpc(client, method, params=None, id=1):
    r = client.post(
        "/mcp/",
        headers=HEADERS,
        json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}},
    )
    assert r.status_code == 200, r.text
    data = (
        next(line[5:] for line in r.text.splitlines() if line.startswith("data:"))
        if "data:" in r.text
        else r.text
    )
    return json.loads(data)


@pytest.fixture
def client(config, renderer, fake_cups):
    with TestClient(build_app(config, renderer.client(), fake_cups.cups())) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_tools_list_over_http(client):
    names = {t["name"] for t in rpc(client, "tools/list")["result"]["tools"]}
    assert {"print_document", "preview_document", "list_printers"} <= names


def test_print_over_http(client):
    out = rpc(
        client, "tools/call", {"name": "print_document", "arguments": {"content": "<p>x</p>"}}
    )
    assert out["result"]["isError"] is False
    assert json.loads(out["result"]["content"][0]["text"])["job_id"] == "Office-Laser-7"


def test_preview_over_http_carries_an_image(client):
    out = rpc(client, "tools/call", {"name": "preview_document", "arguments": {"content": "x"}})
    assert [c["type"] for c in out["result"]["content"]] == ["text", "image"]
    assert out["result"]["content"][1]["mimeType"] == "image/png"


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("nope", {}),
        ("print_document", {"content": "x", "url": "http://x"}),
        ("cancel_job", {"job_id": "-a"}),
    ],
)
def test_failures_are_tool_errors_not_http_errors(client, name, args):
    out = rpc(client, "tools/call", {"name": name, "arguments": args})
    assert out["result"]["isError"] is True
    assert out["result"]["content"][0]["text"]


def test_renderer_outage_is_a_tool_error(config, renderer, fake_cups):
    renderer.fail = httpx.ConnectError("refused")
    with TestClient(build_app(config, renderer.client(), fake_cups.cups())) as c:
        out = rpc(c, "tools/call", {"name": "print_document", "arguments": {"content": "x"}})
    assert out["result"]["isError"] is True
    assert "Renderer unreachable" in out["result"]["content"][0]["text"]

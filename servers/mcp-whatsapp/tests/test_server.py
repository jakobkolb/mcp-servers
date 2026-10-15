import json

import pytest
from mcp_whatsapp.server import build_app
from starlette.testclient import TestClient

from .conftest import ALICE, BOB

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
def client(config, bridge):
    app = build_app(config(ALICE), bridge.client())
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_tools_list_over_http(client):
    out = rpc(client, "tools/list")
    names = {t["name"] for t in out["result"]["tools"]}
    assert {"list_available_chats", "get_pairing_qr"} <= names
    assert not [n for n in names if "send" in n]


def test_tool_call_over_http(client):
    out = rpc(client, "tools/call", {"name": "list_messages", "arguments": {"limit": 1}})
    assert out["result"]["isError"] is False
    assert json.loads(out["result"]["content"][0]["text"])[0]["id"] == "a3"


def test_disallowed_chat_over_http_looks_like_a_missing_one(client):
    denied = rpc(client, "tools/call", {"name": "get_chat", "arguments": {"chat_jid": BOB}})
    missing = rpc(
        client, "tools/call", {"name": "get_chat", "arguments": {"chat_jid": "x@s.whatsapp.net"}}
    )
    assert denied["result"]["isError"] is True
    assert denied["result"] == missing["result"]


@pytest.mark.parametrize(
    ("name", "args"),
    [("nope", {}), ("list_chats", {"limit": "x"}), ("get_auth_status", {"extra": 1})],
)
def test_failures_are_tool_errors_not_http_errors(client, name, args):
    out = rpc(client, "tools/call", {"name": name, "arguments": args})
    assert out["result"]["isError"] is True
    assert out["result"]["content"][0]["text"]


def test_bridge_outage_is_a_tool_error(config, bridge):
    import httpx

    bridge.fail = httpx.ConnectError("refused")
    with TestClient(build_app(config(ALICE), bridge.client())) as c:
        out = rpc(c, "tools/call", {"name": "get_auth_status", "arguments": {}})
    assert out["result"]["isError"] is True
    assert "bridge" in out["result"]["content"][0]["text"]

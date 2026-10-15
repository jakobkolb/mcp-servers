import json
from collections.abc import Callable

import httpx
import pytest
from mcp_whatsapp.bridge import BridgeClient
from mcp_whatsapp.config import Config
from mcp_whatsapp.tools import WhatsAppTools
from mcp_whatsapp.whatsapp import NOT_FOUND, NotFound, Store

from .conftest import ALICE, API, BOB, FakeBridge


@pytest.fixture
def tools(config: Callable[..., Config], bridge: FakeBridge) -> Callable[..., WhatsAppTools]:
    def make(*allowed: str) -> WhatsAppTools:
        cfg = config(*allowed)
        return WhatsAppTools(Store(cfg), BridgeClient(bridge.client()))

    return make


def call(t: WhatsAppTools, name: str, **args):
    [content] = t.call(name, args)
    return json.loads(content.text)


EXPECTED = {
    "list_available_chats",
    "list_chats",
    "get_chat",
    "list_messages",
    "get_message_context",
    "search_contacts",
    "get_auth_status",
    "get_pairing_qr",
}


def test_exposes_exactly_the_read_only_tools(tools):
    listed = {t.name: t for t in tools().list_tools()}
    assert set(listed) == EXPECTED
    assert not [n for n in listed if any(w in n for w in ("send", "download", "delete", "write"))]


def test_every_tool_declares_a_strict_schema(tools):
    for t in tools().list_tools():
        assert t.input_schema["type"] == "object"
        assert t.input_schema["additionalProperties"] is False, t.name
        assert t.description and len(t.description) > 20


def test_available_chats_description_points_at_the_allowlist(tools):
    desc = next(t for t in tools().list_tools() if t.name == "list_available_chats").description
    assert "WHATSAPP_ALLOWED_CHATS" in desc


def test_pairing_description_mentions_rotation(tools):
    desc = next(t for t in tools().list_tools() if t.name == "get_pairing_qr").description
    assert "rotate" in desc and "again" in desc


# ---- argument validation --------------------------------------------------


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("list_chats", {"bogus": 1}),
        ("list_chats", {"limit": "ten"}),
        ("list_chats", {"limit": 0}),
        ("list_chats", {"limit": 101}),
        ("list_chats", {"page": -1}),
        ("list_chats", {"sort_by": "jid"}),
        ("get_chat", {}),
        ("get_chat", {"chat_jid": 5}),
        ("get_message_context", {"message_id": "a1"}),  # chat_jid is required
        ("list_messages", {"limit": 1.5}),
        ("search_contacts", {}),
        ("get_auth_status", {"x": 1}),
    ],
)
def test_bad_arguments_are_rejected_before_any_work(tools, bridge, name, args):
    with pytest.raises(ValueError):
        tools(ALICE).call(name, args)
    assert bridge.requests == []


def test_unknown_tool(tools):
    with pytest.raises(ValueError, match="Unknown tool"):
        tools().call("send_message", {"recipient": "x", "message": "y"})


# ---- data tools -----------------------------------------------------------


def test_data_tools_return_json_text(tools):
    t = tools(ALICE)
    assert [m["id"] for m in call(t, "list_messages", limit=2)] == ["a3", "a2"]
    assert call(t, "get_chat", chat_jid=ALICE)["name"] == "Alice"
    assert call(t, "get_message_context", message_id="a2", chat_jid=ALICE)["message"]["id"] == "a2"
    assert call(t, "list_chats")[0]["jid"] == ALICE
    assert call(t, "search_contacts", query="ali")[0]["jid"] == ALICE


def test_disallowed_chat_error_is_the_generic_one(tools):
    with pytest.raises(NotFound, match=NOT_FOUND):
        tools(ALICE).call("get_chat", {"chat_jid": BOB})


def test_data_tools_do_not_touch_the_bridge(tools, bridge):
    tools(ALICE).call("list_messages", {})
    tools(ALICE).call("list_available_chats", {})
    assert bridge.requests == []


# ---- pairing, driven by contract/api.json ---------------------------------

STATUS_CASES = API["auth_status"]["cases"]
QR_CASES = API["auth_qr"]["cases"]


@pytest.mark.parametrize("case", STATUS_CASES, ids=lambda c: c["name"])
def test_get_auth_status_relays_the_contract(tools, bridge, case):
    bridge.state = case["state"]
    assert call(tools(), "get_auth_status") == case["body"]


@pytest.mark.parametrize("case", QR_CASES, ids=lambda c: c["name"])
def test_get_pairing_qr_relays_the_contract(tools, bridge, case):
    bridge.state = case["state"]
    out = call(tools(), "get_pairing_qr")
    if case["http"] == 200:
        assert out == case["body"]
    else:  # no code: say why instead of failing, so the agent can retry or stop
        assert out["qr"] is None
        assert out["status"] == case["state"]["status"]
        assert out["note"]


def test_pairing_tools_work_without_a_database_and_with_an_empty_allowlist(bridge):
    t = WhatsAppTools(
        Store(Config(db_path="/nonexistent/messages.db")), BridgeClient(bridge.client())
    )
    assert call(t, "get_auth_status") == {"status": "unpaired"}


def test_bridge_down_is_a_clear_error(tools, bridge):
    bridge.fail = httpx.ConnectError("refused")
    for name in ("get_auth_status", "get_pairing_qr"):
        with pytest.raises(RuntimeError, match="bridge"):
            tools().call(name, {})


def test_bridge_error_status_is_a_clear_error(tools, bridge):
    bridge.http_status = 500
    for name in ("get_auth_status", "get_pairing_qr"):
        with pytest.raises(RuntimeError, match="500"):
            tools().call(name, {})

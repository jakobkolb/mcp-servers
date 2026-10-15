"""Tool table and dispatch. Read-only by construction: nothing here can send."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jsonschema
from mcp.types import TextContent, Tool

from .bridge import BridgeClient
from .whatsapp import MAX_LIMIT, Store

_S: dict[str, Any] = {"type": "string"}


def _int(lo: int, hi: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "integer", "minimum": lo}
    if hi is not None:
        out["maximum"] = hi
    return out


_LIMIT = _int(1, MAX_LIMIT)
_PAGE = _int(0)


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class _Tool:
    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[..., Any]


class WhatsAppTools:
    def __init__(self, store: Store, bridge: BridgeClient) -> None:
        self._tools = [
            _Tool(
                "list_available_chats",
                "List ALL chats (JID, name, last activity; never message content), including"
                " chats that are not allowed. Use this to choose the values for the"
                " WHATSAPP_ALLOWED_CHATS setting (comma-separated JIDs).",
                _schema({}),
                store.list_available_chats,
            ),
            _Tool(
                "list_chats",
                "List allowed WhatsApp chats, optionally filtered by name or JID.",
                _schema(
                    {
                        "query": _S,
                        "limit": _LIMIT,
                        "page": _PAGE,
                        "sort_by": {"enum": ["last_active", "name"]},
                    }
                ),
                store.list_chats,
            ),
            _Tool(
                "get_chat",
                "Get an allowed chat by JID.",
                _schema({"chat_jid": _S}, ["chat_jid"]),
                store.get_chat,
            ),
            _Tool(
                "list_messages",
                "Search messages in allowed chats, newest first. after/before are ISO-8601"
                " (no timezone means UTC); sender is a phone number; query matches message text."
                " Each message has sender_name: the name saved in the phone's contacts, else the"
                " sender's profile name, null if unknown.",
                _schema(
                    {
                        "after": _S,
                        "before": _S,
                        "sender": _S,
                        "chat_jid": _S,
                        "query": _S,
                        "limit": _LIMIT,
                        "page": _PAGE,
                    }
                ),
                store.list_messages,
            ),
            _Tool(
                "get_message_context",
                "Get the messages around one message of an allowed chat (use the id and"
                " chat_jid from list_messages).",
                _schema(
                    {
                        "message_id": _S,
                        "chat_jid": _S,
                        "before": _int(0, 50),
                        "after": _int(0, 50),
                    },
                    ["message_id", "chat_jid"],
                ),
                store.get_message_context,
            ),
            _Tool(
                "search_contacts",
                "Search the allowed direct chats by name or phone number.",
                _schema({"query": _S, "limit": _LIMIT}, ["query"]),
                store.search_contacts,
            ),
            _Tool(
                "get_auth_status",
                "WhatsApp pairing status: paired, unpaired or logged_out.",
                _schema({}),
                bridge.status,
            ),
            _Tool(
                "get_pairing_qr",
                "Get the raw QR payload for linking this server as a WhatsApp device. Render it"
                " as a QR code for the user to scan in WhatsApp > Linked devices. Codes rotate"
                " about every 20 seconds: if the scan fails, call this again and show the new"
                " code. Check get_auth_status afterwards. Returns qr=null when there is no code.",
                _schema({}),
                lambda: self._qr(bridge),
            ),
        ]
        self._by_name = {t.name: t for t in self._tools}

    @staticmethod
    def _qr(bridge: BridgeClient) -> dict[str, Any]:
        out = bridge.qr()
        if out is not None:
            return out
        return {
            "qr": None,
            **bridge.status(),
            "note": "No pairing code available (already paired, or the next code is not ready yet)",
        }

    def list_tools(self) -> list[Tool]:
        return [
            Tool(name=t.name, description=t.description, input_schema=t.schema) for t in self._tools
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        tool = self._by_name.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        try:
            jsonschema.validate(arguments, tool.schema)
        except jsonschema.ValidationError as e:
            raise ValueError(f"Invalid arguments for {name}: {e.message}") from None
        return [TextContent(type="text", text=json.dumps(tool.run(**arguments)))]

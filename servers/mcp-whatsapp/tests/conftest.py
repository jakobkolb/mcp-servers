"""Shared fixtures. The schema and the bridge API come from contract/, the same files
the Go bridge is built and tested against, so neither side can drift unnoticed."""

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from mcp_whatsapp.config import Config

CONTRACT = Path(__file__).resolve().parents[1] / "contract"
SCHEMA = (CONTRACT / "schema.sql").read_text()
API = json.loads((CONTRACT / "api.json").read_text())["endpoints"]

ALICE = "4915111@s.whatsapp.net"
BOB = "4915222@s.whatsapp.net"
FAMILY = "120363@g.us"


def ts(day: int, h: int, m: int = 0) -> str:
    return f"2026-01-{day:02d}T{h:02d}:{m:02d}:00Z"


# (id, chat, sender, content, timestamp, is_from_me, media_type)
MESSAGES = [
    ("a1", ALICE, "4915111", "hello from alice", ts(2, 9), 0, ""),
    ("a2", ALICE, "4900", "hi alice", ts(2, 9, 5), 1, ""),
    ("a3", ALICE, "4915111", "photo", ts(2, 10, 30), 0, "image"),
    ("b1", BOB, "4915222", "top secret", ts(2, 11), 0, ""),
    ("b2", BOB, "4915222", "bob 100% sure_thing", ts(2, 11, 5), 0, ""),
    ("f1", FAMILY, "4915111", "family hello", ts(2, 8), 0, ""),
    ("a1", FAMILY, "4915333", "same id, other chat", ts(2, 7), 0, ""),
]
# (user, name): Alice is saved in the address book, 4915333 only has a profile name.
# Bob only writes in his own chat, so his name must never show up unless BOB is allowed.
CONTACTS = [("4915111", "Alice Saved"), ("4915333", "Carla Profile"), ("4915222", "Bobby Saved")]
CHATS = [
    (ALICE, "Alice", ts(2, 10, 30)),
    (BOB, "Bob Secret", ts(2, 11, 5)),
    (FAMILY, "Family", ts(2, 8)),
]


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = tmp_path / "messages.db"
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO chats VALUES (?, ?, ?)", CHATS)
    db.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)", MESSAGES)
    db.executemany("INSERT INTO contacts VALUES (?, ?)", CONTACTS)
    db.commit()
    db.close()
    return str(path)


@pytest.fixture
def config(db_path: str) -> Callable[..., Config]:
    def make(*allowed: str) -> Config:
        return Config(allowed_chats=frozenset(allowed), db_path=db_path, bridge_url="http://bridge")

    return make


class FakeBridge:
    """Answers like the Go bridge, driven entirely by contract/api.json."""

    def __init__(self) -> None:
        self.state = {"status": "unpaired", "qr": ""}
        self.requests: list[tuple[str, str]] = []
        self.fail: Exception | None = None
        self.http_status: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if self.fail:
            raise self.fail
        if self.http_status:
            return httpx.Response(self.http_status, text="boom")
        for endpoint in API.values():
            if (endpoint["method"], endpoint["path"]) == (request.method, request.url.path):
                for case in endpoint["cases"]:
                    if case["state"] == self.state:
                        return httpx.Response(case["http"], json=case["body"])
                raise AssertionError(f"contract/api.json has no case for state {self.state}")
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://bridge", transport=httpx.MockTransport(self.handler))


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()

"""Real Go code against real Python code. Skipped when no Go toolchain is available."""

import os
import shutil
import socket
import sqlite3
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from mcp_whatsapp.bridge import BridgeClient
from mcp_whatsapp.config import Config
from mcp_whatsapp.tools import WhatsAppTools
from mcp_whatsapp.whatsapp import Store

from .conftest import ALICE, BOB, FAMILY, SCHEMA, ts

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None or os.getenv("SKIP_GO_INTEGRATION"),
    reason="needs the Go toolchain",
)


def go(*args: str, **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=300, **kw
    )


@pytest.fixture(scope="module")
def seeded(tmp_path_factory) -> Path:
    """A database written by the bridge's own store code."""
    d = tmp_path_factory.mktemp("store")
    go("run", "./cmd/fixture", str(d))
    return d / "messages.db"


def test_go_created_the_contract_schema(seeded):
    def shape(db: sqlite3.Connection) -> dict[str, list[tuple]]:
        return {
            t: [r[1:4] for r in db.execute(f"PRAGMA table_info({t})")]  # name, type, notnull
            for t in ("chats", "messages")
        }

    reference = sqlite3.connect(":memory:")
    reference.executescript(SCHEMA)
    assert shape(sqlite3.connect(seeded)) == shape(reference)


def test_python_reads_what_go_wrote(seeded):
    s = Store(Config(allowed_chats=frozenset({ALICE, FAMILY}), db_path=str(seeded)))
    alice = s.list_messages(chat_jid=ALICE)
    assert [
        (m["id"], m["content"], m["timestamp"], m["is_from_me"], m["media_type"]) for m in alice
    ] == [
        ("a3", "photo", ts(2, 10, 30), False, "image"),
        ("a2", "hi alice", ts(2, 9, 5), True, ""),
        ("a1", "hello from alice", ts(2, 9), False, ""),
    ]
    assert s.get_message_context("a1", FAMILY)["message"]["content"] == "same id, other chat"
    assert [c["jid"] for c in s.list_available_chats()] == [BOB, ALICE, FAMILY]


def test_timestamp_filters_agree_across_the_language_boundary(seeded):
    s = Store(Config(allowed_chats=frozenset({ALICE}), db_path=str(seeded)))
    # Go wrote 10:05 CET; Python asks in UTC and in CET for the same instant.
    for after in (ts(2, 9, 5), "2026-01-02T10:05:00+01:00"):
        assert [m["id"] for m in s.list_messages(after=after)] == ["a3"]


def test_allowlist_holds_on_a_database_written_by_go(seeded):
    s = Store(Config(allowed_chats=frozenset({ALICE}), db_path=str(seeded)))
    assert "top secret" not in str(s.list_messages(query="secret", limit=100))
    assert s.list_chats() and all(c["jid"] == ALICE for c in s.list_chats())


@pytest.fixture(scope="module")
def running_bridge(tmp_path_factory):
    d = tmp_path_factory.mktemp("bridge")
    binary = d / "whatsapp-bridge"
    go("build", "-o", str(binary), "./cmd/whatsapp-bridge")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "WHATSAPP_STORE_DIR": str(d / "store"), "WHATSAPP_BRIDGE_PORT": str(port)}
    proc = subprocess.Popen(
        [str(binary)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{base}/api/auth/status", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            pytest.fail("bridge did not start")
        yield proc, base, d
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_real_bridge_serves_the_contract_to_the_python_client(running_bridge):
    _, base, _ = running_bridge
    t = WhatsAppTools(Store(Config()), BridgeClient(httpx.Client(base_url=base)))
    assert BridgeClient(httpx.Client(base_url=base)).status() == {"status": "unpaired"}
    [qr] = t.call("get_pairing_qr", {})
    out = __import__("json").loads(qr.text)
    # Offline: no code yet. Online: a real code. Either way the shape is the contract's.
    assert (out["qr"] is None and out["status"] == "unpaired") or (
        isinstance(out["qr"], str) and out["qr"]
    )


def test_real_bridge_stays_up_unpaired_and_has_no_other_routes(running_bridge):
    proc, base, d = running_bridge
    time.sleep(3)  # WhatsApp unreachable or waiting for a scan: it must not exit
    assert proc.poll() is None
    for method, path in (
        ("POST", "/api/send"),
        ("GET", "/api/send"),
        ("POST", "/api/download"),
        ("POST", "/api/auth/status"),
    ):
        r = httpx.request(method, base + path, json={"recipient": "x", "message": "y"})
        assert r.status_code in (404, 405), (method, path, r.status_code)
    assert (d / "store" / "messages.db").exists()  # schema created at startup

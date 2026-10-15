"""Shared fixtures: fake CUPS client binaries and a fake Gotenberg.

The fake lp/lpstat/cancel print exactly what CUPS 2.4 prints (captured from a real
cupsd with LANG=C), so the real Cups wrapper and its parsers run unchanged.
"""

import io
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp_print.config import Config
from mcp_print.cups import Cups
from pypdf import PdfWriter

SINCE = "Thu Oct 15 21:03:55 2026"

FAKE_CUPS = r"""#!{python}
import json, os, sys
path = os.environ["FAKE_CUPS"]
state = json.load(open(path))
cmd, args = os.path.basename(sys.argv[0]), sys.argv[1:]
data = sys.stdin.buffer.read() if cmd == "lp" else b""
with open(path + ".log", "a") as log:
    log.write(json.dumps({{"cmd": cmd, "args": args, "stdin": data.decode("latin1"),
                          "lang": os.environ.get("LANG")}}) + "\n")
printers = state["printers"]
def fail(msg):
    sys.stderr.write(msg + "\n"); sys.exit(1)
if cmd == "lpstat":
    if args == ["-d"]:
        d = state.get("default")
        print(f"system default destination: {{d}}" if d else "no system default destination")
    elif args in (["-p"], ["-a"]):
        if not printers:
            fail("lpstat: No destinations added.")
        for p in printers:
            if args == ["-p"]:
                name = p["name"]
                if p["state"] == "disabled":
                    reason = p.get("reason", "Paused")
                    print(f"printer {{name}} disabled since {SINCE} -\n\t{{reason}}")
                elif p["state"] == "printing":
                    print(f"printer {{name}} now printing {{name}}-1.  enabled since {SINCE}")
                else:
                    print(f"printer {{name}} is idle.  enabled since {SINCE}")
            elif p.get("accepting", True):
                print(f"{{p['name']}} accepting requests since {SINCE}")
            else:
                print(f"{{p['name']}} not accepting requests since {SINCE} -\n\tout of toner")
    elif args[:1] == ["-W"] and args[2] == "-o":
        names = {{p["name"] for p in printers}}
        if len(args) > 3 and args[3] not in names:
            fail(f'lpstat: Invalid destination name in list "{{args[3]}}".')
        for j in state["jobs"].get(args[1], []):
            if len(args) == 3 or j.startswith(args[3] + "-"):
                print(f"{{j:<24}}root              1024   {SINCE}")
elif cmd == "lp":
    dest = args[args.index("-d") + 1]
    p = next((p for p in printers if p["name"] == dest), None)
    if p is None:
        fail("lp: Error - The printer or class does not exist.")
    if not p.get("accepting", True):
        fail(f'lp: Destination "{{dest}}" is not accepting jobs.')
    print(f"request id is {{dest}}-7 (0 file(s))")
elif cmd == "cancel":
    if args[0] not in state["jobs"].get("not-completed", []):
        fail(f"cancel: cancel-job failed: Job #{{args[0].rsplit('-', 1)[1]}} does not exist.")
"""


class FakeCups:
    def __init__(self, tmp: Path) -> None:
        self.state_path = tmp / "cups.json"
        self.state: dict[str, Any] = {
            "printers": [
                {"name": "Office-Laser", "state": "idle"},
                {"name": "Kitchen", "state": "printing"},
                {"name": "Old", "state": "disabled", "reason": "out of toner", "accepting": False},
            ],
            "default": "Office-Laser",
            "jobs": {"not-completed": ["Office-Laser-3", "Kitchen-4"], "completed": ["Old-1"]},
        }
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        script = FAKE_CUPS.format(python=sys.executable, SINCE=SINCE)
        for name in ("lp", "lpstat", "cancel"):
            exe = bin_dir / name
            exe.write_text(script)
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        self.env = {"PATH": str(bin_dir), "FAKE_CUPS": str(self.state_path), "LANG": "de_DE"}

    def cups(self) -> Cups:
        self.state_path.write_text(json.dumps(self.state))
        return Cups(env=self.env)

    @property
    def calls(self) -> list[dict[str, Any]]:
        log = Path(str(self.state_path) + ".log")
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def make_pdf(pages: int) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeRenderer:
    """Answers like Gotenberg's two Chromium HTML routes."""

    def __init__(self) -> None:
        self.pages = 2
        self.requests: list[tuple[str, dict[str, str], str]] = []
        self.fail: Exception | None = None
        self.http_status: int | None = None

    @staticmethod
    def _parts(request: httpx.Request) -> tuple[dict[str, str], str]:
        body = request.read().decode()
        fields = dict(re.findall(r'name="(\w+)"\r\n\r\n(.*?)\r\n--', body, re.S))
        doc = re.search(
            r'filename="index.html"\r\nContent-Type: text/html\r\n\r\n(.*?)\r\n--', body, re.S
        )
        assert doc, "the document must be sent as index.html"
        return fields, doc.group(1)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise self.fail
        if self.http_status:
            return httpx.Response(self.http_status, text="boom")
        fields, doc = self._parts(request)
        self.requests.append((request.url.path, fields, doc))
        if request.url.path == "/forms/chromium/convert/html":
            return httpx.Response(200, content=make_pdf(self.pages))
        if request.url.path == "/forms/chromium/screenshot/html":
            return httpx.Response(200, content=PNG)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://renderer", transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake_cups(tmp_path: Path) -> FakeCups:
    return FakeCups(tmp_path)


@pytest.fixture
def renderer() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture
def config() -> Config:
    return Config(renderer_url="http://renderer")


@pytest.fixture
def pdf_of():
    return make_pdf


@pytest.fixture
def png() -> bytes:
    return PNG

"""Client for the bridge's loopback REST API (contract/api.json)."""

from typing import Any

import httpx


class BridgeClient:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def _get(self, path: str) -> httpx.Response:
        try:
            return self._http.get(path)
        except httpx.HTTPError as e:
            raise RuntimeError(f"WhatsApp bridge unreachable: {e}") from e

    def _ok(self, r: httpx.Response) -> dict[str, Any]:
        if r.status_code != 200:
            raise RuntimeError(f"WhatsApp bridge returned HTTP {r.status_code}")
        body: dict[str, Any] = r.json()
        return body

    def status(self) -> dict[str, Any]:
        return self._ok(self._get("/api/auth/status"))

    def qr(self) -> dict[str, Any] | None:
        """The current pairing code, or None when there is none."""
        r = self._get("/api/auth/qr")
        return None if r.status_code == 404 else self._ok(r)

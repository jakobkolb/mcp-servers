import asyncio

import pytest
from mcp_obsidian.main import amain


@pytest.mark.parametrize("transport", ["sse", "http", "websocket"])
def test_unsupported_transport_is_an_error(tmp_path, monkeypatch, transport):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("MCP_TRANSPORT", transport)

    with pytest.raises(ValueError, match="Unsupported MCP_TRANSPORT"):
        asyncio.run(amain())

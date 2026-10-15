"""Environment-driven configuration."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Empty means no chat content is served at all.
    allowed_chats: frozenset[str] = frozenset()
    db_path: str = "/store/messages.db"
    bridge_url: str = "http://127.0.0.1:8080"


def load_config() -> Config:
    return Config(
        allowed_chats=frozenset(
            c.strip() for c in os.getenv("WHATSAPP_ALLOWED_CHATS", "").split(",") if c.strip()
        ),
        db_path=os.getenv("WHATSAPP_DB_PATH", "/store/messages.db"),
        bridge_url=os.getenv("WHATSAPP_BRIDGE_URL", "http://127.0.0.1:8080"),
    )

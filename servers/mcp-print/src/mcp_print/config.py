"""Environment-driven configuration. CUPS_SERVER is read by the CUPS client itself."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    renderer_url: str = "http://127.0.0.1:3000"
    # Empty means every printer CUPS offers.
    allowed_printers: frozenset[str] = frozenset()
    # Empty means the CUPS default destination.
    default_printer: str = ""
    max_pages: int = 20
    max_copies: int = 10
    max_content_bytes: int = 2_000_000


def load_config() -> Config:
    return Config(
        renderer_url=os.getenv("PRINT_RENDERER_URL", "http://127.0.0.1:3000"),
        allowed_printers=frozenset(
            p.strip() for p in os.getenv("PRINT_ALLOWED_PRINTERS", "").split(",") if p.strip()
        ),
        default_printer=os.getenv("PRINT_DEFAULT_PRINTER", "").strip(),
        max_pages=int(os.getenv("PRINT_MAX_PAGES", "20")),
        max_copies=int(os.getenv("PRINT_MAX_COPIES", "10")),
        max_content_bytes=int(os.getenv("PRINT_MAX_CONTENT_BYTES", "2000000")),
    )

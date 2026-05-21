from __future__ import annotations

from io import StringIO
from typing import Any

import frontmatter as fm_lib
from ruamel.yaml import YAML


def _make_yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True
    y.width = 120
    return y


def parse(content: str) -> tuple[dict[str, Any], str]:
    """
    Split a markdown string into (frontmatter_dict, body_text).

    Returns ({}, full_content) if no frontmatter block is present.
    Never raises on malformed YAML.
    """
    try:
        post = fm_lib.loads(content)
    except Exception:
        return {}, content
    return dict(post.metadata), post.content


def serialize(frontmatter: dict[str, Any]) -> str:
    """Serialize a frontmatter dict to YAML without the surrounding --- delimiters."""
    y = _make_yaml()
    stream = StringIO()
    y.dump(dict(frontmatter), stream)
    return stream.getvalue()


def extract_tags(fm: dict[str, Any]) -> list[str]:
    """Return frontmatter tags normalised to #-prefixed strings."""
    raw = fm.get("tags", [])
    if isinstance(raw, str):
        raw = [raw]
    return [f"#{t.lstrip('#')}" for t in raw]


def build_note_content(frontmatter: dict[str, Any] | None, body: str) -> str:
    """Combine frontmatter and body into a complete note string."""
    if not frontmatter:
        return body
    return f"---\n{serialize(frontmatter)}---\n{body}"

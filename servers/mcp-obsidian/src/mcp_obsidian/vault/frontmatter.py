from typing import Any

import frontmatter as fm_lib  # type: ignore[import-untyped]
import yaml


def parse(content: str) -> tuple[dict[str, Any], str]:
    """
    Split a markdown string into (frontmatter_dict, body_text).

    If the note has malformed YAML, keep the note readable by returning empty
    metadata and the original content.
    """
    try:
        post = fm_lib.loads(content)
    except Exception:
        return {}, content
    return dict(post.metadata), post.content


def serialize(frontmatter: dict[str, Any]) -> str:
    """Serialize a frontmatter dict without the surrounding --- delimiters."""
    return yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def build_note_content(frontmatter: dict[str, Any] | None, body: str) -> str:
    """Combine frontmatter and body into a complete markdown note."""
    if not frontmatter:
        return body
    return f"---\n{serialize(frontmatter)}---\n{body}"

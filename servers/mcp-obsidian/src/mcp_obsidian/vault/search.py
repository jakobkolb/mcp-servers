from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp_obsidian.vault.frontmatter import extract_tags
from mcp_obsidian.vault.frontmatter import parse as parse_fm

_INLINE_TAG_RE = re.compile(r"(?<!\w)#([a-zA-Z0-9_/\-äöüÄÖÜß]+)")
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def _note_has_tag(fm_dict: dict[str, Any], body: str, tag: str) -> bool:
    """Return True if the note carries tag (with or without leading #)."""
    normalized = tag.lstrip("#").lower()
    for t in extract_tags(fm_dict):
        if t.lstrip("#").lower() == normalized:
            return True
    body_no_code = _CODE_BLOCK_RE.sub("", body)
    body_no_headings = "\n".join(
        line for line in body_no_code.splitlines() if not re.match(r"^#{1,6}\s", line)
    )
    for m in _INLINE_TAG_RE.finditer(body_no_headings):
        if m.group(1).lower() == normalized:
            return True
    return False


def search_notes(
    vault_root: str,
    query: str,
    search_content: bool = True,
    search_frontmatter: bool = False,
    case_sensitive: bool = False,
    limit: int = 5,
    path_filter: str | None = None,
    search_limit_max: int = 20,
    include_frontmatter: bool = False,
    tag_filter: str | None = None,
    frontmatter_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Regex full-text search across vault .md files."""
    limit = min(limit, search_limit_max)
    flags = 0 if case_sensitive else re.IGNORECASE

    try:
        pattern = re.compile(query, flags)
    except re.error:
        pattern = re.compile(re.escape(query), flags)

    vault = Path(vault_root)
    results: list[dict[str, Any]] = []
    total_found = 0

    for md_file in sorted(vault.rglob("*.md")):
        rel = str(md_file.relative_to(vault))
        if path_filter and not rel.startswith(path_filter):
            continue

        try:
            raw = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fm_dict, body = parse_fm(raw)

        if tag_filter and not _note_has_tag(fm_dict, body, tag_filter):
            continue

        if frontmatter_filter and not all(
            fm_dict.get(k) == v for k, v in frontmatter_filter.items()
        ):
            continue

        content_match = None
        fm_match = None

        if search_content and body:
            content_match = pattern.search(body)

        if search_frontmatter:
            # frontmatter section is everything before the body
            body_start = raw.find(body) if body else len(raw)
            fm_section = raw[:body_start]
            if fm_section:
                fm_match = pattern.search(fm_section)

        if not content_match and not fm_match:
            continue

        total_found += 1
        if len(results) >= limit:
            continue

        if content_match:
            body_lines = body.splitlines()
            body_before = body[: content_match.start()]
            body_line_num = body_before.count("\n") + 1
            body_start_in_raw = raw.find(body) if body in raw else 0
            fm_line_count = raw[:body_start_in_raw].count("\n")
            file_line_num = fm_line_count + body_line_num

            start = max(0, body_line_num - 2)
            end = min(len(body_lines), body_line_num + 1)
            snippet = "\n".join(body_lines[start:end])
            score = 1.0 if case_sensitive else 0.5
            frontmatter_match = fm_match is not None
        else:
            file_line_num = 1
            snippet = raw[:200]
            score = 0.5
            frontmatter_match = True

        entry: dict[str, Any] = {
            "path": rel,
            "snippet": snippet,
            "score": score,
            "line": file_line_num,
            "frontmatter_match": frontmatter_match,
        }
        if include_frontmatter:
            entry["frontmatter"] = fm_dict
        results.append(entry)

    return {
        "results": results,
        "total_found": total_found,
        "query": query,
        "search_mode": "regex",
    }


def list_all_tags(vault_root: str) -> dict[str, Any]:
    """Return all tags in the vault with occurrence counts."""
    vault = Path(vault_root)
    tag_data: dict[str, dict[str, Any]] = {}

    for md_file in vault.rglob("*.md"):
        try:
            raw = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fm_dict, body = parse_fm(raw)

        for normalized in extract_tags(fm_dict):
            if normalized not in tag_data:
                tag_data[normalized] = {"tag": normalized, "count": 0, "sources": set()}
            tag_data[normalized]["count"] += 1
            tag_data[normalized]["sources"].add("frontmatter")

        body_no_code = _CODE_BLOCK_RE.sub("", body)
        body_no_headings = "\n".join(
            line for line in body_no_code.splitlines() if not re.match(r"^#{1,6}\s", line)
        )
        for m in _INLINE_TAG_RE.finditer(body_no_headings):
            normalized = f"#{m.group(1)}"
            if normalized not in tag_data:
                tag_data[normalized] = {"tag": normalized, "count": 0, "sources": set()}
            tag_data[normalized]["count"] += 1
            tag_data[normalized]["sources"].add("inline")

    sorted_tags = sorted(tag_data.values(), key=lambda t: (-t["count"], t["tag"]))
    for t in sorted_tags:
        t["sources"] = sorted(t["sources"])

    return {"tags": sorted_tags, "total_unique": len(sorted_tags)}

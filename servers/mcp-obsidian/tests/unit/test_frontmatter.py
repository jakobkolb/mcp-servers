from mcp_obsidian.vault import build_note_content, parse


def test_parse_returns_frontmatter_and_body(note):
    frontmatter, body = parse(note)
    assert frontmatter["title"] == "Hello"
    assert not frontmatter["completed"]
    assert "Body text." in body


def test_parse_without_frontmatter_returns_empty_metadata():
    content = "# Just a title\n\nAnd some body text.\n"

    frontmatter, body = parse(content)

    assert frontmatter == {}
    assert body.rstrip("\n") == content.rstrip("\n")


def test_parse_malformed_yaml_returns_original_content():
    content = "---\n: bad: yaml: here\n---\n\nBody text.\n"

    frontmatter, body = parse(content)

    assert frontmatter == {}
    assert body == content


def test_parse_frontmatter_list_tags():
    content = "---\ntags:\n  - project\n  - gtd\n---\n\nBody text.\n"

    frontmatter, body = parse(content)

    assert frontmatter["tags"] == ["project", "gtd"]
    assert "Body text." in body


def test_build_note_content_without_frontmatter_returns_body():
    body = "# Hello\n\nJust text.\n"

    assert build_note_content({}, body) == body


def test_build_note_content_with_frontmatter():
    result = build_note_content({"title": "Hello", "completed": False}, "Body text.\n")

    assert result.startswith("---\n")
    assert "title: Hello" in result
    assert "completed: false" in result
    assert result.endswith("Body text.\n")

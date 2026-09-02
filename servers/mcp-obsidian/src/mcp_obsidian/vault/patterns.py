from __future__ import annotations

import re

# Matches inline #tags in markdown body text. Excludes headings (caller's responsibility).
# Segments are joined by "/" or "-" but a tag never ends on one, so prose such as
# "#context/*-Tags" yields "#context" rather than a phantom "#context/".
_TAG_SEGMENT = r"[a-zA-Z0-9_äöüÄÖÜß]+"
INLINE_TAG_RE = re.compile(rf"(?<!\w)#({_TAG_SEGMENT}(?:[/\-]{_TAG_SEGMENT})*)")

# Matches fenced code blocks (``` ... ```) including multi-line. Used to strip code before parsing.
CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)

# Matches [[wiki-links]], capturing only the target (strips |alias and #heading suffixes).
WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

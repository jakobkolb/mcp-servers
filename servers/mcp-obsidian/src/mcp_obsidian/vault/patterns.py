from __future__ import annotations

import re

# Matches inline #tags in markdown body text. Excludes headings (caller's responsibility).
INLINE_TAG_RE = re.compile(r"(?<!\w)#([a-zA-Z0-9_/\-äöüÄÖÜß]+)")

# Matches fenced code blocks (``` ... ```) including multi-line. Used to strip code before parsing.
CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)

# Matches [[wiki-links]], capturing only the target (strips |alias and #heading suffixes).
WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

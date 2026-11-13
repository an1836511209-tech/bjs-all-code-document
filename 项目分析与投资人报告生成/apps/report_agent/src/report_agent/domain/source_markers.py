"""Remove report provenance metadata from visible prose, without removing facts."""
from __future__ import annotations

import re

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# Older model outputs also use XML-style <src .../> metadata. Attribute values
# may contain > or line breaks; don't let those terminate the tag prematurely.
_SRC_TAG_RE = re.compile(r'''<src\b(?:[^>"']|"[^"]*"|'[^']*')*/\s*>''', re.DOTALL | re.IGNORECASE)


def strip_source_markers(text: str) -> str:
    return _SRC_TAG_RE.sub("", _COMMENT_RE.sub("", text))

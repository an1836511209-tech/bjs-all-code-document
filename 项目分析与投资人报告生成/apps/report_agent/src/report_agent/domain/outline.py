"""Load required section list from outline.md.

Used by QualityChecker to detect missing_section issues.
"""

from __future__ import annotations

import re
from pathlib import Path

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_PREFIX_RE = re.compile(r"^[一二三四五六七八九十]+、\s*")


def outline_loader(path: str | None = None) -> list[str]:
    """Parse a report outline markdown for required top-level sections.

    Returns titles that start with "## 一、 / ## 二、 …" (CJK ordinal + 顿号).
    Headings without that prefix are documentation about the format (e.g. a
    "## 表格格式" note) rather than report sections, so they are skipped.
    When ``path`` is None or missing, returns an empty list so the caller
    can degrade to warn-only.
    """
    if path is None:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        m = _HEADING_RE.match(line.strip())
        if not m:
            continue
        title = m.group(1).strip()
        if not title or not _PREFIX_RE.match(title):
            continue
        out.append(title)
    return out

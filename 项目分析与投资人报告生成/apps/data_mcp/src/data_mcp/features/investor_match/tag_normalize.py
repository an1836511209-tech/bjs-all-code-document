"""Shared track-tag string cleanup for investor match / DMP label_name."""

from __future__ import annotations


def strip_wrapping_quotes(tag: str) -> str:
    """Remove paired outer ASCII quotes; leave internal quotes untouched."""
    text = str(tag).strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text

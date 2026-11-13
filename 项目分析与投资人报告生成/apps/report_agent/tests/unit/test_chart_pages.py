"""Chart pages must be flagged: their states live in shapes, not in words."""

from __future__ import annotations

from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from report_agent.infrastructure.materials.parser import (  # noqa: E402
    CHART_ELEMENT_THRESHOLD,
    _chart_pages,
)


def _pdf(tmp_path, *, dots: int, lines: int = 0) -> str:
    document = pymupdf.open()
    page = document.new_page()
    for index in range(dots):
        page.draw_circle(pymupdf.Point(60 + index * 6, 120), 3)
    for line in range(lines):
        page.insert_text((60, 200 + line * 14), "填" * 30, fontsize=9)
    target = tmp_path / "sample.pdf"
    document.save(target)
    document.close()
    return str(target)


def test_page_with_many_graphics_is_a_chart_page(tmp_path):
    path = _pdf(tmp_path, dots=CHART_ELEMENT_THRESHOLD + 10)
    assert _chart_pages(Path(path)) == {1}


def test_text_rich_page_is_not_a_chart_page(tmp_path):
    path = _pdf(tmp_path, dots=CHART_ELEMENT_THRESHOLD + 10, lines=20)
    assert _chart_pages(Path(path)) == set()


def test_page_with_few_graphics_is_not_a_chart_page(tmp_path):
    path = _pdf(tmp_path, dots=3)
    assert _chart_pages(Path(path)) == set()


def test_missing_file_is_tolerated(tmp_path):
    assert _chart_pages(tmp_path / "does-not-exist.pdf") == set()


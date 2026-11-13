"""Platform placeholder messages must not derail report generation."""

from __future__ import annotations

import pytest

from report_agent.application.user_request import (
    DEFAULT_REPORT_REQUEST,
    normalize_user_request,
)


@pytest.mark.parametrize(
    "message",
    [
        "",
        "   ",
        "总结文档内容",
        "请总结文档内容",
        "总结文档",
        "请总结一下文档内容",
        "Summarize the document",
        "summarize document.",
    ],
)
def test_placeholder_or_empty_with_uploads_becomes_report_request(message: str) -> None:
    assert normalize_user_request(message, has_uploads=True) == DEFAULT_REPORT_REQUEST


def test_empty_without_uploads_still_defaults_to_report_request() -> None:
    assert normalize_user_request("", has_uploads=False) == DEFAULT_REPORT_REQUEST


def test_explicit_user_instruction_is_preserved() -> None:
    message = "请基于材料生成投资人匹配报告，重点关注新能源赛道"
    assert normalize_user_request(message, has_uploads=True) == message


def test_summarize_phrase_without_uploads_is_preserved() -> None:
    # Without files we should not rewrite; the caller may be asking a text-only question.
    assert normalize_user_request("总结文档内容", has_uploads=False) == "总结文档内容"


def test_compound_instruction_is_not_treated_as_placeholder() -> None:
    message = "总结文档内容，然后生成投资人匹配报告"
    assert normalize_user_request(message, has_uploads=True) == message

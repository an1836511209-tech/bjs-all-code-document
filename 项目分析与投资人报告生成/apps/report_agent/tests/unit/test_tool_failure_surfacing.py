"""工具失败必须让上级看见：不能变成"等你回答"，也不能记成成功。"""

from __future__ import annotations

import json

from report_agent.application.runs import (
    ToolTrace,
    _failed_tool_names,
    _has_unresolved_tool_failure,
    _payload_status,
)


def _trace(*items: tuple[str, str, object]) -> list[ToolTrace]:
    return [
        ToolTrace(sequence=index, tool=name, status=status, output=output)
        for index, (name, status, output) in enumerate(items, start=1)
    ]


def test_a_tool_that_raised_counts_as_failure():
    trace = _trace(("edit_file", "error", "boom"))
    assert _has_unresolved_tool_failure(trace) is True


def test_a_tool_that_returned_a_failed_json_body_counts_as_failure():
    """`add_report_comments` 拒收批注时返回的是普通 JSON，不是 ToolMessage error。"""
    body = json.dumps({"status": "error", "problems": [{"problem": "x"}]}, ensure_ascii=False)
    trace = _trace(("add_report_comments", "completed", body))
    assert _has_unresolved_tool_failure(trace) is True
    assert _failed_tool_names(trace) == ["add_report_comments"]


def test_partial_and_empty_are_not_failures():
    partial = json.dumps({"status": "partial", "tags": []})
    empty = json.dumps({"status": "empty", "summary": "未查到"})
    trace = _trace(
        ("query_track_labels", "completed", partial),
        ("query_cbex_listing_financials", "completed", empty),
    )
    assert _has_unresolved_tool_failure(trace) is False


def test_a_retry_that_succeeds_clears_the_failure():
    """只看每个工具的**最新**一次调用——修好了就不该算失败。"""
    broken = json.dumps({"status": "error"})
    fixed = json.dumps({"status": "ok"})
    trace = _trace(
        ("add_report_comments", "completed", broken),
        ("add_report_comments", "completed", fixed),
    )
    assert _has_unresolved_tool_failure(trace) is False


def test_registry_soft_failure_does_not_fail_the_run():
    """工商查不到或数据源不可用要弹名称卡片，不能把整轮收成失败。"""
    body = json.dumps(
        {"status": "failed", "summary": "数据源暂不可用，本次未获取到合适数据"},
        ensure_ascii=False,
    )
    question = json.dumps(
        {"status": "needs_user_input", "gate": "company_registry", "question": "请提供精确名称"},
        ensure_ascii=False,
    )
    trace = _trace(
        ("query_company_registry", "completed", body),
        ("ask_user", "completed", question),
    )
    assert _has_unresolved_tool_failure(trace) is False
    assert _failed_tool_names(trace) == []


def test_registry_exception_still_fails_the_run():
    trace = _trace(("query_company_registry", "error", "boom"))
    assert _has_unresolved_tool_failure(trace) is True


def test_plain_text_output_is_not_mistaken_for_a_failure():
    trace = _trace(("read_file", "completed", "普通文本，status 不是 JSON"))
    assert _has_unresolved_tool_failure(trace) is False


def test_status_extraction_handles_dict_and_string():
    assert _payload_status({"status": "failed"}) == "failed"
    assert _payload_status('{"status": "failed"}') == "failed"
    assert _payload_status("no json here") == ""
    assert _payload_status(None) == ""
    assert _payload_status('{"no_status": 1}') == ""


def test_failed_tool_names_is_sorted_and_deduplicated():
    body = json.dumps({"status": "invalid_arguments"})
    trace = _trace(
        ("b_tool", "completed", body),
        ("a_tool", "error", "x"),
        ("b_tool", "completed", body),
    )
    assert _failed_tool_names(trace) == ["a_tool", "b_tool"]

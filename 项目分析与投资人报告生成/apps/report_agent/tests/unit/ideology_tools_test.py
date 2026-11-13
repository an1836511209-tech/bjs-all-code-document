"""Unit tests for ``report_agent.harness.ideology_tools``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from report_agent.harness.ideology_tools import TOOL_NAME, build_ideology_tools

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ideology_minimal.yaml"


class TestBuildIdeologyTools:
    def test_returns_one_tool_named_correctly(self) -> None:
        tools = build_ideology_tools(FIXTURE_PATH)
        assert len(tools) == 1
        assert tools[0].name == TOOL_NAME

    def test_tool_description_is_substantial(self) -> None:
        tools = build_ideology_tools(FIXTURE_PATH)
        assert tools[0].description is not None
        assert len(tools[0].description) >= 50

    def test_missing_dictionary_raises(self) -> None:
        missing = Path(__file__).parent / "tmp" / "absent.yaml"
        with pytest.raises(FileNotFoundError):
            build_ideology_tools(missing)


class TestOutputFormat:
    def _call(self, text: str) -> dict[str, object]:
        tools = build_ideology_tools(FIXTURE_PATH)
        raw = tools[0].invoke(text)
        result: dict[str, object] = json.loads(raw)
        return result

    def test_compact_json_no_newlines(self) -> None:
        tools = build_ideology_tools(FIXTURE_PATH)
        raw = tools[0].invoke("错误A错误B")
        assert "\n" not in raw
        assert "  " not in raw

    def test_chinese_suggestion_not_escaped(self) -> None:
        tools = build_ideology_tools(FIXTURE_PATH)
        raw = tools[0].invoke("错误A")
        assert "\\u" not in raw
        assert "正确A" in raw

    def test_match_has_required_fields(self) -> None:
        result = self._call("错误A")
        matches = result["matches"]
        assert isinstance(matches, list)
        assert len(matches) == 1
        m = matches[0]
        for field in (
            "rule_id",
            "category_label",
            "severity",
            "original",
            "suggestion",
            "context",
            "path",
            "offset",
            "length",
        ):
            assert field in m

    def test_summary_counts(self) -> None:
        result = self._call("错误A错误A2025年")
        assert result["summary"]["total"] == 3
        assert result["summary"]["by_category"] == {
            "测试类别A": 2,
            "测试类别C": 1,
        }
        assert result["summary"]["by_severity"] == {"block": 3}

    def test_empty_text_returns_zero(self) -> None:
        result = self._call("")
        assert result["matches"] == []
        assert result["summary"]["total"] == 0
        assert result["summary"]["by_category"] == {}
        assert result["summary"]["by_severity"] == {}

    def test_no_hits_returns_zero(self) -> None:
        result = self._call("完全干净的文本")
        assert result["matches"] == []
        assert result["summary"]["total"] == 0
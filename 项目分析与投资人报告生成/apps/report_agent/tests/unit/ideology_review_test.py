"""Unit tests for ``report_agent.application.ideology_review``."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from report_agent.application.ideology_review import (
    CONTEXT_HALF_WIDTH,
    IdeologyReviewer,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ideology_minimal.yaml"
LOCAL_TMP = Path(__file__).parent / "tmp"


def _reviewer() -> IdeologyReviewer:
    return IdeologyReviewer(FIXTURE_PATH)


def _tmp_file(name: str, content: str) -> Path:
    """Write to a per-test temp file under the unit-tests folder, not OS tmp."""
    LOCAL_TMP.mkdir(exist_ok=True)
    target = LOCAL_TMP / f"{uuid.uuid4().hex}_{name}"
    target.write_text(content, encoding="utf-8")
    return target


class TestInit:
    def test_missing_file_raises_filenotfound(self) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            IdeologyReviewer(LOCAL_TMP / "absent.yaml")

    def test_directory_path_raises_value_error(self) -> None:
        LOCAL_TMP.mkdir(exist_ok=True)
        with pytest.raises(ValueError, match="not a file"):
            IdeologyReviewer(LOCAL_TMP)

    def test_invalid_yaml_raises_value_error(self) -> None:
        broken = _tmp_file("broken.yaml", ":\n  - [")
        with pytest.raises(ValueError, match="YAML parse failed"):
            IdeologyReviewer(broken)

    def test_missing_categories_raises(self) -> None:
        bad = _tmp_file("no_cat.yaml", "version: '1.0'\n")
        with pytest.raises(ValueError, match="categories"):
            IdeologyReviewer(bad)

    def test_missing_pattern_raises(self) -> None:
        bad = _tmp_file(
            "no_pat.yaml",
            (
                "version: '1.0'\n"
                "categories:\n"
                "  - id: c\n"
                "    label: C\n"
                "    items:\n"
                "      - rule_id: X\n"
                "        suggestion: 's'\n"
                "        severity: block\n"
            ),
        )
        with pytest.raises(ValueError, match=r"X\)\.pattern"):
            IdeologyReviewer(bad)

    def test_bad_severity_raises(self) -> None:
        bad = _tmp_file(
            "bad_sev.yaml",
            (
                "version: '1.0'\n"
                "categories:\n"
                "  - id: c\n"
                "    label: C\n"
                "    items:\n"
                "      - rule_id: X\n"
                "        pattern: 'p'\n"
                "        suggestion: 's'\n"
                "        severity: critical\n"
            ),
        )
        with pytest.raises(ValueError, match=r"X\)\.severity"):
            IdeologyReviewer(bad)

    def test_duplicate_rule_id_raises(self) -> None:
        bad = _tmp_file(
            "dup.yaml",
            (
                "version: '1.0'\n"
                "categories:\n"
                "  - id: c1\n"
                "    label: A\n"
                "    items:\n"
                "      - rule_id: DUP\n"
                "        pattern: 'a'\n"
                "        suggestion: 'x'\n"
                "        severity: block\n"
                "  - id: c2\n"
                "    label: B\n"
                "    items:\n"
                "      - rule_id: DUP\n"
                "        pattern: 'b'\n"
                "        suggestion: 'y'\n"
                "        severity: block\n"
            ),
        )
        with pytest.raises(ValueError, match="duplicate rule_id 'DUP'"):
            IdeologyReviewer(bad)

    def test_invalid_regex_raises(self) -> None:
        bad = _tmp_file(
            "bad_re.yaml",
            (
                "version: '1.0'\n"
                "categories:\n"
                "  - id: c\n"
                "    label: C\n"
                "    items:\n"
                "      - rule_id: X\n"
                "        pattern: '[unclosed'\n"
                "        suggestion: 's'\n"
                "        severity: block\n"
            ),
        )
        with pytest.raises(ValueError, match=r"X\)\.pattern failed to compile"):
            IdeologyReviewer(bad)

    def test_minimal_fixture_loads_three_rules(self) -> None:
        reviewer = _reviewer()
        assert len(reviewer.rules) == 3
        rule_ids = {rule.rule_id for rule in reviewer.rules}
        assert rule_ids == {"T1", "T2", "T3"}


class TestReview:
    def test_single_string_hit(self) -> None:
        reviewer = _reviewer()
        matches = reviewer.review("这段包含错误A需要改")
        assert len(matches) == 1
        m = matches[0]
        assert m.rule_id == "T1"
        assert m.original == "错误A"
        assert m.severity == "block"
        assert m.category_label == "测试类别A"
        assert m.offset == 4
        assert m.length == 3
        assert m.path == "/workspace/report/report.md"

    def test_no_hit_returns_empty(self) -> None:
        assert _reviewer().review("完全干净") == ()

    def test_multi_choice_string(self) -> None:
        reviewer = _reviewer()
        text = "出现错误B与错误C两处"
        matches = reviewer.review(text)
        rule_ids = sorted(m.rule_id for m in matches)
        assert rule_ids == ["T2", "T2"]
        originals = sorted(m.original for m in matches)
        assert originals == ["错误B", "错误C"]

    def test_regex_hit(self) -> None:
        reviewer = _reviewer()
        matches = reviewer.review("事件发生在2025年")
        assert len(matches) == 1
        assert matches[0].rule_id == "T3"
        assert matches[0].original == "2025年"

    def test_context_clipping_at_start(self) -> None:
        text = "AB" + "错误A" + "CD"
        matches = _reviewer().review(text)
        assert len(matches) == 1
        assert matches[0].context.startswith(text[:1])
        assert matches[0].context == text

    def test_context_clipping_at_end(self) -> None:
        text = "AB" + "错误A"
        matches = _reviewer().review(text)
        assert len(matches) == 1
        assert matches[0].context == text
        assert len(matches[0].context) <= CONTEXT_HALF_WIDTH * 2 + 3

    def test_multiple_occurrences(self) -> None:
        text = "错误A错误A错误A"
        matches = _reviewer().review(text)
        assert len(matches) == 3
        assert all(m.rule_id == "T1" for m in matches)
        offsets = [m.offset for m in matches]
        assert offsets == [0, 3, 6]

    def test_cross_category_matches(self) -> None:
        text = "错误A是分类A，错误B是分类B，2025年是分类C"
        matches = _reviewer().review(text)
        labels = {m.category_label for m in matches}
        assert labels == {"测试类别A", "测试类别B", "测试类别C"}

    def test_empty_text_returns_empty(self) -> None:
        assert _reviewer().review("") == ()

    def test_explicit_path_overrides_default(self) -> None:
        matches = _reviewer().review("错误A", path="/workspace/x.md")
        assert matches[0].path == "/workspace/x.md"

    def test_context_field_uses_constant(self) -> None:
        """Hit at the middle of a long body: context has constant half-width."""
        prefix = "前" * 50
        suffix = "后" * 50
        text = prefix + "错误A" + suffix
        matches = _reviewer().review(text)
        assert len(matches) == 1
        ctx = matches[0].context
        assert ctx.startswith("前" * CONTEXT_HALF_WIDTH)
        assert ctx.endswith("后" * CONTEXT_HALF_WIDTH)


def teardown_module() -> None:
    """Best-effort cleanup of the local tmp folder."""
    if LOCAL_TMP.exists():
        shutil.rmtree(LOCAL_TMP, ignore_errors=True)
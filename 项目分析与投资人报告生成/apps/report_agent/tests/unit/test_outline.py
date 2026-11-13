"""Unit tests for outline_loader."""

from __future__ import annotations

import textwrap


def test_outline_loader_returns_empty_for_missing_path():
    from report_agent.domain.outline import outline_loader

    assert outline_loader() == []
    assert outline_loader("/nonexistent/path.md") == []


def test_outline_loader_parses_cjk_ordinal_titles():
    from report_agent.domain.outline import outline_loader

    md = textwrap.dedent(
        """\
        # 报告头部

        ## 一、报告头部
        body
        ## 二、项目分析
        body
        ## 三、市场分析
        body
        ## 四、对标与估值参考
        body
        ## 五、投资匹配分析
        body
        ## 六、匹配投资人明细
        body
        """
    )
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md)
        path = f.name
    try:
        titles = outline_loader(path)
        assert titles == [
            "一、报告头部",
            "二、项目分析",
            "三、市场分析",
            "四、对标与估值参考",
            "五、投资匹配分析",
            "六、匹配投资人明细",
        ]
    finally:
        import os

        os.unlink(path)


def test_outline_loader_ignores_h3_and_above():
    from report_agent.domain.outline import outline_loader

    md = textwrap.dedent(
        """\
        ## 一、报告头部
        body
        ### （一）项目概况
        body
        ## 二、项目分析
        body
        """
    )
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md)
        path = f.name
    try:
        titles = outline_loader(path)
        assert titles == ["一、报告头部", "二、项目分析"]
    finally:
        import os

        os.unlink(path)

from report_agent.infrastructure.word.md_parser import parse_report_markdown

EVIDENCE = "evidence_e422ec0e6a5646f8b0608282bf3f5e10"


def _parse(markdown: str):
    return parse_report_markdown(
        markdown,
        report_id="report_test",
        title="测试报告",
        company_name="示例公司",
        title_evidence_id=EVIDENCE,
    )


def test_citation_between_table_rows_keeps_every_row() -> None:
    report = _parse(
        f"""
## 六、匹配投资人明细

| 投资人名称 | 投资人类型 | 受让理由分析 |
|-----------|-----------|------------|
| 甲公司 | 基金 | 理由甲 |
<!-- cite: {EVIDENCE} -->
| 乙公司 | 基金 | 理由乙 |
<!-- cite: {EVIDENCE} -->
"""
    )
    tables = report.sections[0].tables
    assert len(tables) == 1
    assert [row.values[0] for row in tables[0].rows] == ["甲公司", "乙公司"]
    assert all(row.citations[0].evidence_id == EVIDENCE for row in tables[0].rows)


def test_trailing_citation_still_covers_an_uncited_table() -> None:
    report = _parse(
        f"""
## 四、对标

| 证券代码 | 证券名称 |
|---------|---------|
| 600863.SH | 华能蒙电 |
| 600795.SH | 国电电力 |
<!-- cite: {EVIDENCE} -->
"""
    )
    rows = report.sections[0].tables[0].rows
    assert [row.values[1] for row in rows] == ["华能蒙电", "国电电力"]
    assert all(row.citations[0].evidence_id == EVIDENCE for row in rows)


def test_bullet_src_marker_stripped_and_parsed() -> None:
    report = _parse(
        """
## 三、项目介绍

- 宇航级芯片：VDMOS 全系列。<!-- src: material parse_materials /data/blocks/5/text ; 原文：VDMOS全系列 -->
"""
    )
    bullets = report.sections[0].bullet_items
    assert len(bullets) == 1
    assert bullets[0].text == "宇航级芯片：VDMOS 全系列。"
    assert "<!--" not in bullets[0].text
    assert bullets[0].src is not None
    assert bullets[0].src.kind == "material"
    assert bullets[0].src.tool == "parse_materials"
    assert bullets[0].src.pointer == "/data/blocks/5/text"
    assert "VDMOS" in bullets[0].src.note

"""Fill a one-pager Word template with :class:`OnePagerContent`.

The templates shipped under ``skills/one-pager/assets`` are not ordinary
flowing documents: the whole page is a set of floating text boxes anchored to
one body paragraph. Two consequences drive this module.

1. Every placeholder can be split across several ``w:r`` runs (``{{联系人名称}}``
   spans three), so replacement happens on the *merged paragraph text*, never
   run by run.
2. Each shape is wrapped in ``mc:AlternateContent``, so the same placeholder
   occurs twice — once in the DrawingML ``Choice`` branch and once in the VML
   ``Fallback``. Both must be rewritten or the two branches drift apart.

The investor table is not part of the template; it is appended to the body.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from lxml import etree

from report_agent.domain.one_pager import (
    PLACEHOLDERS_BY_BUSINESS_TYPE,
    BusinessType,
    OnePagerContent,
)

TEMPLATE_FILENAMES: dict[BusinessType, str] = {
    BusinessType.PROPERTY: "产权模板.docx",
    BusinessType.CAPITAL: "增资模板.docx",
}

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}·]+?)\s*\}\}")

BODY_FONT = "仿宋_GB2312"
HEADING_FONT = "黑体"

INVESTOR_HEADERS = ("序号", "来源", "投资人类型", "投资人名称", "匹配理由")
#: 附页左右留白（pt）。模板的页边距是 0（整页都是浮动文本框），
#: 正文流里的表格会直接顶到纸边，这里显式留出与第一页相近的空隙。
INVESTOR_PAGE_MARGIN_PT = 36.0

# 列宽比例（pt）。序号/来源/类型只需要窄列，把宽度让给匹配理由，
# 否则理由列每行只有十来个字，表格会被撑得很长。
INVESTOR_WIDTHS_PT = (44.0, 60.0, 86.0, 90.0, 315.0)
NO_INVESTOR_TEXT = "暂无可用匹配数据"

INVESTOR_SOURCE_LABELS: dict[str, str] = {"internal": "内部库", "web": "网络"}


def _tag(name: str) -> str:
    return f"{{{W}}}{name}"


def default_assets_dir() -> Path:
    """Installed wheels carry their own templates; source checkouts use skills.

    A non-editable Linux install moves this module into site-packages. Walking
    up to ``skills`` there worked only when a Python-version-specific bind
    mount happened to supply the templates.
    """
    bundled = Path(__file__).resolve().parents[2] / "resources" / "one_pager"
    if bundled.is_dir():
        return bundled
    return Path(__file__).resolve().parents[4] / "skills" / "one-pager" / "assets"


def resolve_template(business_type: BusinessType, *, assets_dir: Path | None = None) -> Path:
    """Locate the template for ``business_type``.

    Raises ``FileNotFoundError`` when the asset is absent — a missing template
    is a deployment fault, never something to paper over at render time.
    """
    directory = assets_dir or default_assets_dir()
    path = directory / TEMPLATE_FILENAMES[business_type]
    if not path.is_file():
        raise FileNotFoundError(f"one-pager template not found: {path}")
    return path


def _own_paragraphs(textbox: etree._Element):
    """Paragraphs belonging to ``textbox`` itself, excluding nested text boxes."""
    for paragraph in textbox.iter(_tag("p")):
        ancestor = paragraph.getparent()
        while ancestor is not None and ancestor.tag != _tag("txbxContent"):
            ancestor = ancestor.getparent()
        if ancestor is textbox:
            yield paragraph


def iter_textbox_paragraphs(root: etree._Element):
    """Every paragraph inside any text box, including VML fallbacks."""
    for textbox in root.iter(_tag("txbxContent")):
        yield from _own_paragraphs(textbox)


def _run_text_nodes(paragraph: etree._Element) -> list[etree._Element]:
    return list(paragraph.iter(_tag("t")))


def _merged_text(nodes: list[etree._Element]) -> str:
    return "".join(node.text or "" for node in nodes)


#: Placeholder prefixes that must render in the heading face. Everything else is
#: body copy.
_HEADING_PLACEHOLDERS = ("项目介绍标题", "项目亮点标题", "项目名称")


def _normalize_document_fonts(root: etree._Element) -> int:
    """把全文的仿宋/黑体家族收敛到两个字体名，返回改写的 run 数。

    只改"已经有显式字体"的 run：模板里 25 个 run 写的是 ``方正仿宋_GB2312``
    （另一个字库），用户机器上很可能没装，WPS 会报"缺失字体"并回退渲染——
    同一段里中文和数字因此看起来不是一种字体。

    按家族（名字里含"仿宋"/"黑体"）而不是精确匹配，是因为模板和后续代码路径
    都可能引入新的变体；精确匹配只能挡住已知的那一个。
    """
    changed = 0
    for run in root.iter(_tag("r")):
        properties = run.find(_tag("rPr"))
        fonts = properties.find(_tag("rFonts")) if properties is not None else None
        if fonts is None:
            continue  # 没写字体 = 继承样式，不动它
        east = fonts.get(_tag("eastAsia")) or ""
        if "仿宋" in east:
            _force_run_font(run, BODY_FONT)
            changed += 1
        elif "黑体" in east:
            _force_run_font(run, HEADING_FONT)
            changed += 1
    return changed


def _font_for_placeholders(names: tuple[str, ...]) -> str:
    return HEADING_FONT if any(n.startswith(_HEADING_PLACEHOLDERS) for n in names) else BODY_FONT


def _force_run_font(run: etree._Element, name: str) -> None:
    """Pin one font on a raw ``w:r`` element.

    ``w:rPr`` must be the run's first child and ``w:rFonts`` the first thing in
    it, so both are created at position 0 when missing.

    The template is hand-made: two of its boxes were authored in 仿宋 while the
    remaining thirty use 仿宋_GB2312. Inheriting each paragraph's own font (the
    old behaviour) therefore produced a page where one highlight paragraph had
    visibly different letterforms from its two neighbours.
    """
    properties = run.find(_tag("rPr"))
    if properties is None:
        properties = etree.Element(_tag("rPr"))
        run.insert(0, properties)
    fonts = properties.find(_tag("rFonts"))
    if fonts is None:
        fonts = etree.Element(_tag("rFonts"))
        properties.insert(0, fonts)
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(_tag(attribute), name)


def _rewrite_paragraph(
    paragraph: etree._Element, values: dict[str, str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Replace every ``{{placeholder}}`` in one paragraph.

    The merged text goes into the first ``w:t`` and the rest are emptied, then
    the whole paragraph is pinned to one font — heading placeholders to 黑体, the
    rest to 仿宋_GB2312 — so a stray template font cannot survive. Returns
    ``(filled, unresolved)``; unresolved names are blanked rather than left in
    the output.
    """
    nodes = _run_text_nodes(paragraph)
    if not nodes:
        return (), ()
    merged = _merged_text(nodes)
    if "{{" not in merged:
        return (), ()

    filled: list[str] = []
    unresolved: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name in values:
            filled.append(name)
            return values[name]
        unresolved.append(name)
        return ""

    replaced = _PLACEHOLDER_RE.sub(substitute, merged)
    _write_text_with_breaks(nodes[0], replaced)
    for node in nodes[1:]:
        node.text = ""
        node.set(XML_SPACE, "preserve")
    if filled:
        font = _font_for_placeholders(tuple(filled))
        for run in paragraph.iter(_tag("r")):
            _force_run_font(run, font)
    return tuple(filled), tuple(unresolved)


def _write_text_with_breaks(node: etree._Element, text: str) -> None:
    """把文本写入 ``w:t``，并把换行转成 ``<w:br/>``。

    一页纸的正文框只有一个段落。分点写法（``1.小标题。正文`` 每点一行）如果不转
    成真正的换行，Word 会把所有条目连成一整段——客户端看到的就是小标题和正文挤在
    一起、看不出分了几个点。
    """
    lines = text.split("\n")
    node.text = lines[0]
    node.set(XML_SPACE, "preserve")
    if len(lines) == 1:
        return
    run = node.getparent()
    if run is None:
        return
    index = list(run).index(node)
    for offset, line in enumerate(lines[1:], start=1):
        line_break = etree.Element(_tag("br"))
        text_node = etree.Element(_tag("t"))
        text_node.text = line
        text_node.set(XML_SPACE, "preserve")
        run.insert(index + offset * 2 - 1, line_break)
        run.insert(index + offset * 2, text_node)


def template_placeholders(docx_path: Path) -> frozenset[str]:
    """Placeholder names found in a template.

    Read from the merged text of each text-box paragraph: scanning individual
    ``w:t`` nodes misses any placeholder the template splits across runs.
    """
    document = Document(str(docx_path))
    names: set[str] = set()
    for paragraph in iter_textbox_paragraphs(document.element.body):
        merged = _merged_text(_run_text_nodes(paragraph))
        names.update(match.group(1).strip() for match in _PLACEHOLDER_RE.finditer(merged))
    return frozenset(names)


def missing_placeholders(
    docx_path: Path, business_type: BusinessType
) -> tuple[str, ...]:
    """Required placeholders the template does not actually contain."""
    present = template_placeholders(docx_path)
    return tuple(
        name for name in PLACEHOLDERS_BY_BUSINESS_TYPE[business_type] if name not in present
    )


def _set_run_font(run, *, name: str, size_pt: float, bold: bool = False) -> None:
    run.font.name = name
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run_properties = run._element.get_or_add_rPr()
    fonts = run_properties.find(_tag("rFonts"))
    if fonts is None:
        fonts = etree.SubElement(run_properties, _tag("rFonts"))
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(_tag(attribute), name)


def _apply_borders(table) -> None:
    properties = table._tbl.tblPr
    borders = etree.SubElement(properties, _tag("tblBorders"))
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = etree.SubElement(borders, _tag(edge))
        element.set(_tag("val"), "single")
        element.set(_tag("sz"), "4")
        element.set(_tag("space"), "0")
        element.set(_tag("color"), "808080")


def _apply_cell_margins(table, *, top: int = 110, bottom: int = 110,
                        left: int = 110, right: int = 110) -> None:
    """设置单元格内边距（单位 dxa，1pt = 20 dxa），避免文字贴边。"""
    properties = table._tbl.tblPr
    existing = properties.find(_tag("tblCellMar"))
    if existing is not None:
        properties.remove(existing)
    cell_margins = etree.SubElement(properties, _tag("tblCellMar"))
    for edge, value in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        element = etree.SubElement(cell_margins, _tag(edge))
        element.set(_tag("w"), str(value))
        element.set(_tag("type"), "dxa")


def _write_cell(cell, text: str, *, bold: bool, size_pt: float = 10.5) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.2
    run = paragraph.add_run(text)
    _set_run_font(run, name=BODY_FONT, size_pt=size_pt, bold=bold)


@dataclass(frozen=True, slots=True)
class OnePagerRenderResult:
    """Rendered bytes plus anything the caller must be told about."""

    content: bytes
    business_type: BusinessType
    template: Path
    filled_placeholders: tuple[str, ...] = ()
    unresolved_placeholders: tuple[str, ...] = ()
    investor_rows: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


class OnePagerAuthor:
    """Render :class:`OnePagerContent` into a filled copy of the template."""

    def __init__(self, *, assets_dir: Path | None = None) -> None:
        self.assets_dir = assets_dir

    def render(self, content: OnePagerContent) -> OnePagerRenderResult:
        business_type = content.business_type
        template = resolve_template(business_type, assets_dir=self.assets_dir)
        document = Document(str(template))

        values = content.placeholder_values()
        unresolved: list[str] = []
        filled: set[str] = set()
        for paragraph in iter_textbox_paragraphs(document.element.body):
            paragraph_filled, paragraph_unresolved = _rewrite_paragraph(paragraph, values)
            filled.update(paragraph_filled)
            unresolved.extend(paragraph_unresolved)

        rows = content.investors
        # 模板整页都是绝对定位的浮动文本框，正文流里追加的任何内容都会压在最上层。
        # 所以投资人表单独成页（附页），既不动一页纸版面，也不会盖住正文。
        if rows:
            self._append_investor_page(document, rows)
        # 风险/非优质信息作为小字放在第二页末尾，不占正文槽位。
        risk_notes = content.risk_notes()
        if risk_notes:
            if not rows:
                document.add_page_break()
            self._append_risk_notes(document, risk_notes)
        # 免责声明单独成页（法律部制式文本）。
        self._append_disclaimer_page(document)
        # 最后统一字体：无论正文、附页还是模板残留的 run，都归到两个字库。
        normalized = _normalize_document_fonts(document.element.body)
        buffer = io.BytesIO()
        document.save(buffer)

        notes: list[str] = []
        if unresolved:
            notes.append(f"模板占位符无对应取值，已清空: {sorted(set(unresolved))}")
        if not rows:
            notes.append("未匹配到投资人，模板无投资人区域，已省略该表")

        return OnePagerRenderResult(
            content=buffer.getvalue(),
            business_type=business_type,
            template=template,
            filled_placeholders=tuple(sorted(filled)),
            unresolved_placeholders=tuple(sorted(set(unresolved))),
            investor_rows=len(rows),
            notes=tuple(notes),
        )

    @staticmethod
    @staticmethod
    def _append_risk_notes(document, notes: tuple[str, ...]) -> None:
        """把风险/非优质信息作为小字放在第二页末尾。

        客户反馈：正文里单开「风险提示」模块会挤掉真正的项目介绍；这些信息
        更适合当脚注——位置上仍在报告内，但不占正文篇幅。
        """
        if not notes:
            return
        heading = document.add_paragraph()
        heading.paragraph_format.space_before = Pt(10)
        heading.paragraph_format.left_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        heading.paragraph_format.right_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        _set_run_font(heading.add_run("风险提示"), name=HEADING_FONT, size_pt=9.0, bold=True)
        for note in notes:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.left_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
            paragraph.paragraph_format.right_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
            _set_run_font(paragraph.add_run(note), name=BODY_FONT, size_pt=8.0)

    @staticmethod
    def _append_disclaimer_page(document) -> None:
        """免责声明单独成页。客户要求：法律部审定的制式文本必须完整出现。"""
        from report_agent.infrastructure.word.authoring import (
            DISCLAIMER_PARAGRAPHS,
            DISCLAIMER_SIGNATURE,
            DISCLAIMER_TITLE,
        )

        document.add_page_break()
        title = document.add_paragraph()
        title.paragraph_format.space_before = Pt(INVESTOR_PAGE_MARGIN_PT)
        title.paragraph_format.space_after = Pt(8)
        title.paragraph_format.left_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        title.paragraph_format.right_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        _set_run_font(title.add_run(DISCLAIMER_TITLE), name=HEADING_FONT, size_pt=13.0, bold=True)
        for text in DISCLAIMER_PARAGRAPHS:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(4)
            paragraph.paragraph_format.left_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
            paragraph.paragraph_format.right_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
            _set_run_font(paragraph.add_run(text), name=BODY_FONT, size_pt=9.0)
        signature = document.add_paragraph()
        signature.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        signature.paragraph_format.space_before = Pt(12)
        _set_run_font(signature.add_run(DISCLAIMER_SIGNATURE), name=BODY_FONT, size_pt=10.5)
    def _printable_width_pt(document) -> float:
        """当前节的可打印宽度（pt）：页宽减去左右页边距。"""
        section = document.sections[0]
        if section.page_width is None:
            return 451.0  # A4 默认页宽减 1 英寸边距
        usable = (
            int(section.page_width)
            - int(section.left_margin or 0)
            - int(section.right_margin or 0)
        )
        return usable / 12700.0  # EMU → pt

    @staticmethod
    def _append_investor_page(document, rows) -> None:
        """把投资人匹配表放到单独一页，按可打印宽度等比缩放列宽。"""
        document.add_page_break()

        heading = document.add_paragraph()
        heading.paragraph_format.space_before = Pt(INVESTOR_PAGE_MARGIN_PT)
        heading.paragraph_format.space_after = Pt(2)
        heading.paragraph_format.left_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        heading.paragraph_format.right_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        _set_run_font(
            heading.add_run("投资人匹配"), name=HEADING_FONT, size_pt=13.0, bold=True
        )

        note = document.add_paragraph()
        note.paragraph_format.space_before = Pt(0)
        note.paragraph_format.space_after = Pt(6)
        note.paragraph_format.left_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        note.paragraph_format.right_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        _set_run_font(
            note.add_run("附：投资机构匹配结果，按匹配理由排序，供参考。"),
            name=BODY_FONT,
            size_pt=8.5,
        )

        body_rows = [
            (
                str(index),
                INVESTOR_SOURCE_LABELS.get(row.source, row.source),
                row.investor_type,
                row.name,
                row.match_reason,
            )
            for index, row in enumerate(rows, start=1)
        ]
        if not body_rows:
            body_rows = [("1", "-", "-", NO_INVESTOR_TEXT, "-")]

        # 模板页宽 595pt，原来的 595pt 列宽合计等于整张纸，右侧会被裁掉；
        # 这里按实际可打印宽度等比缩放。
        usable_pt = OnePagerAuthor._printable_width_pt(document) - 2 * INVESTOR_PAGE_MARGIN_PT
        scale = usable_pt / sum(INVESTOR_WIDTHS_PT)
        widths = tuple(width * scale for width in INVESTOR_WIDTHS_PT)

        table = document.add_table(rows=1 + len(body_rows), cols=len(INVESTOR_HEADERS))
        table.autofit = False
        _apply_borders(table)
        _apply_cell_margins(table)

        # python-docx 只设 cell.width 时 Word 仍会自动均衡列宽；
        # 必须把表格锁定为固定布局并写明总宽，列宽才生效。
        tbl_pr = table._tbl.tblPr
        indent = OxmlElement("w:tblInd")
        indent.set(qn("w:type"), "dxa")
        indent.set(qn("w:w"), str(int(INVESTOR_PAGE_MARGIN_PT * 20)))  # 1pt = 20 dxa
        tbl_pr.append(indent)
        layout = OxmlElement("w:tblLayout")
        layout.set(qn("w:type"), "fixed")
        tbl_pr.append(layout)
        total = OxmlElement("w:tblW")
        total.set(qn("w:type"), "dxa")
        total.set(qn("w:w"), str(int(sum(widths) * 20)))  # 1pt = 20 dxa
        tbl_pr.append(total)
        for index, width in enumerate(widths):
            table.columns[index].width = Pt(width)

        for column, (header, width) in enumerate(zip(INVESTOR_HEADERS, widths)):
            cell = table.cell(0, column)
            cell.width = Pt(width)
            _write_cell(cell, header, bold=True)
        for index, values in enumerate(body_rows, start=1):
            for column, (value, width) in enumerate(zip(values, widths)):
                cell = table.cell(index, column)
                cell.width = Pt(width)
                _write_cell(cell, value, bold=False)

        # 表格下方补一行统计：标的是几家、分别来自哪里，避免附页看着半空
        from collections import Counter

        counted = Counter(
            INVESTOR_SOURCE_LABELS.get(row.source, row.source) for row in rows
        )
        detail = " / ".join(f"{label} {count}" for label, count in counted.items())
        summary = document.add_paragraph()
        summary.paragraph_format.space_before = Pt(8)
        summary.paragraph_format.space_after = Pt(0)
        summary.paragraph_format.left_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        summary.paragraph_format.right_indent = Pt(INVESTOR_PAGE_MARGIN_PT)
        _set_run_font(
            summary.add_run(f"共 {len(rows)} 家投资机构" + (f"（{detail}）" if detail else "")),
            name=BODY_FONT,
            size_pt=9.0,
        )

        # 长表跨页时重复表头
        header_row = table.rows[0]
        tr_pr = header_row._tr.get_or_add_trPr()
        header_flag = OxmlElement("w:tblHeader")
        header_flag.set(qn("w:val"), "true")
        tr_pr.append(header_flag)

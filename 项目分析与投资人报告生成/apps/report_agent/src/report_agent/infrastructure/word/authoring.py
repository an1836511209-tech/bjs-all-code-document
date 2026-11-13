"""Create DOCX reports from simple ReportContent (no inline comments).

Comments are added as a post-processing step via ``add_report_comments`` /
``manage_word_comments``, which call the ``comments_add.py`` script to inject
Word comments by paragraph substring matching.  This decouples comment text
from the report schema and lets the model write comments semantically.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from report_agent.application.report_evidence import validate_report_evidence
from report_agent.domain.report_content import ReportContent, ReportSection
from report_agent.domain.tool_labels import humanize_tool, humanize_tools
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore

#: 报告末尾的法律部制式免责声明。措辞由法律部统一，改动只在这里。
DISCLAIMER_TITLE = "免责声明"

DISCLAIMER_PARAGRAPHS: tuple[str, ...] = (
    "本报告由北京产权交易所（以下简称「本所」）依据项目方提供的材料及公开渠道信息整理编制，"
    "仅供本所会员单位及合格投资者内部参考使用，不构成任何投资建议、要约或要约邀请，"
    "亦不构成本所对标的项目的价值判断、背书或增信。",
    "本报告所载信息来源于项目方提供的材料及公开信息，本所已尽合理努力核实其真实性、"
    "准确性与完整性，但不对上述信息的真实性、准确性、完整性及时效性作出任何明示或默示的"
    "保证。报告中的分析、判断与预测均为编制时点的观点，可能因市场变化、信息更新或项目"
    "实际情况调整而发生变化，本所不承担更新义务。",
    "本报告涉及的投资人匹配结果系基于公开信息与历史投资偏好所作的初步筛选，"
    "不代表相关机构具有投资意向，亦不构成对交易达成的任何承诺。"
    "投资者应自行开展尽职调查，独立作出投资决策，并自行承担由此产生的全部风险与损失。",
    "未经本所书面许可，任何机构或个人不得以任何形式复制、转发、公开披露或用于本报告"
    "约定用途之外的其它目的。因违反上述约定使用本报告而产生的法律责任，由使用方自行承担。",
)

DISCLAIMER_SIGNATURE = "北京产权交易所"

#: 批注来源标签。与 ``harness/word_tools.COMMENT_KIND_LABELS`` 保持一致，
#: 这里复制一份避免 infrastructure → harness 的反向依赖。
_COMMENT_KIND_LABELS: dict[str, str] = {
    "material": "原材料",
    "reasoned": "有因推理",
    "unreasoned": "无因推理",
    "web": "网上来源",
    "web_reasoned": "网上来源推理",
    "mcp": "MCP数据",
}


class WordReportAuthor:
    def __init__(self) -> None:
        #: ``(paragraph_text, comment_text)`` collected from ``ReportText.src``.
        #: Consumed by WordReportService right after the DOCX is written, so
        #: provenance comments are anchored to the paragraph that produced them
        #: instead of being matched later by substring search.
        self._src_comments: list[tuple[str, str]] = []

    def take_src_comments(self) -> list[tuple[str, str]]:
        """Return and clear the pending provenance comments."""
        pending = self._src_comments
        self._src_comments = []
        return pending

    def create(
        self,
        content: ReportContent,
        evidence_store: WorkspaceEvidenceStore,
        destination: Path,
        *,
        report_date: date | None = None,
    ) -> int:
        self._src_comments = []
        validate_report_evidence(content, evidence_store)
        document = Document()
        self._configure_page(document)
        self._configure_styles(document)
        title = document.add_paragraph(style="Title")
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_run = title.add_run(content.title)
        self._set_run_font(title_run, "方正小标宋简体", 22)
        self._bookmark(title, f"report_{content.report_id}_title")
        date_paragraph = document.add_paragraph()
        date_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._set_run_font(
            date_paragraph.add_run((report_date or date.today()).isoformat()),
            "仿宋_GB2312",
            16,
        )

        for section in content.sections:
            self._add_section(document, section)
        if content.missing_items:
            missing_heading = document.add_paragraph("数据缺失说明", style="Heading 1")
            self._set_run_font(missing_heading.runs[0], "黑体", 16)
            for item in content.missing_items:
                paragraph = document.add_paragraph(item.description, style="Body Text")
                self._set_run_font(paragraph.runs[0], "仿宋_GB2312", 16)
        self._add_disclaimer(document)
        destination.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(destination))
        return 0

    def update(
        self,
        content: ReportContent,
        evidence_store: WorkspaceEvidenceStore,
        destination: Path,
        *,
        report_date: date | None = None,
    ) -> int:
        """Deterministically rebuild from current semantic ids; callers version old artifacts."""
        return self.create(content, evidence_store, destination, report_date=report_date)

    def _add_section(
        self,
        document: DocumentObject,
        section: ReportSection,
    ) -> None:
        heading = document.add_paragraph(style=f"Heading {section.heading_level}")
        self._bookmark(heading, f"section_{section.section_id}")
        heading_run = heading.add_run(section.title)
        heading_font = "黑体" if section.heading_level == 1 else "楷体_GB2312"
        heading_size = {1: 18, 2: 16, 3: 14}.get(section.heading_level, 16)
        self._set_run_font(heading_run, heading_font, heading_size)
        for item in section.paragraphs:
            paragraph = document.add_paragraph(style="Body Text")
            run = paragraph.add_run(item.text)
            self._set_run_font(run, "仿宋_GB2312", 14)
            # 元数据行（"字段：值"、页码等）不能被两端对齐拉伸：Body Text 的
            # JUSTIFY + 首行缩进会把短行拉成「标 的 项 目 ： 平 安 银 行」。
            if self._looks_like_metadata(item.text):
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                paragraph.paragraph_format.first_line_indent = Pt(0)
            self._collect_src_comment(item)
        for item in section.bullet_items:
            paragraph = document.add_paragraph(style="List Bullet")
            run = paragraph.add_run(item.text)
            self._set_run_font(run, "仿宋_GB2312", 14)
            self._collect_src_comment(item)
        for table_spec in section.tables:
            if table_spec.title:
                table_title = document.add_paragraph(table_spec.title, style="Heading 2")
                self._set_run_font(table_title.runs[0], "楷体_GB2312", 16)
            table = document.add_table(rows=1, cols=len(table_spec.headers))
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
            self._prevent_row_split(table.rows[0])
            widths = self._column_widths(table_spec.headers, table_spec.rows)
            for index, header in enumerate(table_spec.headers):
                cell = table.rows[0].cells[index]
                cell.width = Inches(widths[index])
                cell.text = header
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                self._format_cell(cell, header=True)
            for row_spec in table_spec.rows:
                cells = table.add_row().cells
                self._prevent_row_split(table.rows[-1])
                for index, value in enumerate(row_spec.values):
                    cells[index].width = Inches(widths[index])
                    paragraph = cells[index].paragraphs[0]
                    self._bookmark(paragraph, f"row_{row_spec.row_id}_{index}")
                    run = paragraph.add_run(value)
                    cells[index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    self._format_cell(cells[index], header=False)
            document.add_paragraph(style="Body Text")

    def _add_disclaimer(self, document: DocumentObject) -> None:
        """在报告末尾追加法律部制式免责声明。

        内容固定、不参与模型生成，也不受证据校验影响：它是报告的一部分，
        但不对应任何 ``src`` 批注。文案集中在 ``DISCLAIMER_*`` 常量里，
        法律部更新措辞时只改这里。
        """
        document.add_page_break()

        heading = document.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.paragraph_format.space_before = Pt(0)
        heading.paragraph_format.space_after = Pt(12)
        self._set_run_font(heading.add_run(DISCLAIMER_TITLE), "方正小标宋简体", 16)

        for block in DISCLAIMER_PARAGRAPHS:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.first_line_indent = Pt(32)  # 首行缩进两字
            paragraph.paragraph_format.line_spacing = 1.5
            self._set_run_font(paragraph.add_run(block), "仿宋_GB2312", 14)

        signature = document.add_paragraph()
        signature.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        signature.paragraph_format.space_before = Pt(24)
        self._set_run_font(signature.add_run(DISCLAIMER_SIGNATURE), "仿宋_GB2312", 14)

    def _collect_src_comment(self, item: object) -> None:
        """Queue a provenance comment for every ``src`` marker on this item.

        一个段落常有多个来源（股权结构、子公司、资质各一条）。旧实现只取第一个
        标记、并拿整段文字当锚点，于是几条批注全落到同一句上——客户看到的是
        "同一段下面几条批注，页码和原文对不上"。有 ``src_anchors`` 就按**句子**
        逐条锚定；没有的（历史报告）退回整段，行为不变。
        """
        anchors = getattr(item, "src_anchors", None) or ()
        if anchors:
            for entry in anchors:
                src = entry.get("src") if isinstance(entry, dict) else None
                anchor = (
                    str(entry.get("anchor") or "").strip()
                    if isinstance(entry, dict)
                    else ""
                )
                self._queue_src_comment(src, anchor or getattr(item, "text", ""))
            return
        self._queue_src_comment(getattr(item, "src", None), getattr(item, "text", ""))

    def _queue_src_comment(self, src: object, anchor: str) -> None:
        if src is None:
            return
        kind_label = _COMMENT_KIND_LABELS.get(getattr(src, "kind", ""), "来源")
        note = (getattr(src, "note", "") or "").strip()
        tool = getattr(src, "tool", "")
        pointer = getattr(src, "pointer", "")
        if not note and tool:
            note = f"来源：{humanize_tool(tool)}" + (
                f"；字段：{pointer}" if pointer else ""
            )
        if not note:
            return
        # 模型会把 src 里的英文工具 id 抄进 note（例如「数据来源：query_track_labels
        # 工具返回的 /data/tags 字段」）。批注面向业务读者，统一换成中文名。
        note = humanize_tools(note)
        self._src_comments.append((anchor, f"【{kind_label}】{note}"))

    @staticmethod
    def _looks_like_metadata(text: str) -> bool:
        """识别「字段：值」这类元数据行，它们不能被两端对齐拉伸。

        典型例子：``标的项目：平安银行股份有限公司``、``报告日期：2025 年 3 月``、
        ``第 6 页``。正文段落够长，JUSTIFY 看起来正常；这些短行会被拉开字间距，
        渲染成「标 的 项 目 ： 平 安 银 行」。
        """
        stripped = str(text or "").strip()
        if not stripped or len(stripped) > 60:
            return False
        if re.fullmatch(r"第\s*\d+\s*页", stripped):
            return True
        return bool(re.match(r"^[^。；;]{1,30}[：:]", stripped))

    @staticmethod
    def _column_widths(headers, rows) -> tuple[float, ...]:
        lengths = [len(str(header)) for header in headers]
        for row in rows:
            for index, value in enumerate(row.values):
                lengths[index] = max(lengths[index], len(value))
        weights = [max(1.0, min(4.5, length / 6)) for length in lengths]
        total = sum(weights)
        return tuple(5.77 * weight / total for weight in weights)

    @staticmethod
    def _format_cell(cell, *, header: bool) -> None:
        tc_pr = cell._tc.get_or_add_tcPr()
        margins = tc_pr.first_child_found_in("w:tcMar")
        if margins is None:
            margins = OxmlElement("w:tcMar")
            tc_pr.append(margins)
        for edge in ("top", "left", "bottom", "right"):
            node = margins.find(qn(f"w:{edge}"))
            if node is None:
                node = OxmlElement(f"w:{edge}")
                margins.append(node)
            node.set(qn("w:w"), "90")
            node.set(qn("w:type"), "dxa")
        if header:
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), "DCE6F1")
            tc_pr.append(shading)
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if header else WD_ALIGN_PARAGRAPH.LEFT
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = Pt(18)
            for run in paragraph.runs:
                WordReportAuthor._set_run_font(run, "宋体", 10.5)
                run.font.bold = header

    @staticmethod
    def _prevent_row_split(row) -> None:
        properties = row._tr.get_or_add_trPr()
        if properties.find(qn("w:cantSplit")) is None:
            properties.append(OxmlElement("w:cantSplit"))

    @staticmethod
    def _bookmark(paragraph, stable_id: str) -> None:
        bookmark_id = str(int(hashlib.sha256(stable_id.encode()).hexdigest()[:7], 16))
        name = "_" + hashlib.sha256(stable_id.encode()).hexdigest()[:30]
        start = OxmlElement("w:bookmarkStart")
        start.set(qn("w:id"), bookmark_id)
        start.set(qn("w:name"), name)
        end = OxmlElement("w:bookmarkEnd")
        end.set(qn("w:id"), bookmark_id)
        paragraph._p.insert(0, start)
        paragraph._p.append(end)

    @staticmethod
    def _configure_page(document: DocumentObject) -> None:
        section = document.sections[0]
        section.start_type = WD_SECTION.NEW_PAGE
        section.page_width = Inches(8.27)
        section.page_height = Inches(11.69)
        section.left_margin = Inches(1.25)
        section.right_margin = Inches(1.25)
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.footer_distance = Inches(0.45)
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        WordReportAuthor._set_run_font(footer.add_run("第 "), "宋体", 9)
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        footer._p.append(field)
        WordReportAuthor._set_run_font(footer.add_run(" 页"), "宋体", 9)

    @staticmethod
    def _configure_styles(document: DocumentObject) -> None:
        specs = {
            "Title": ("方正小标宋简体", 22),
            "Heading 1": ("黑体", 16),
            "Heading 2": ("楷体_GB2312", 16),
            "Heading 3": ("黑体", 14),
            "Body Text": ("仿宋_GB2312", 16),
            "Normal": ("仿宋_GB2312", 16),
        }
        for style_name, (font_name, size) in specs.items():
            style = document.styles[style_name]
            style.font.name = font_name
            style.font.size = Pt(size)
            style.font.color.rgb = None
            WordReportAuthor._set_rfonts(style._element.get_or_add_rPr(), font_name)
        title = document.styles["Title"]
        title.font.color.rgb = RGBColor(0, 0, 0)
        title.paragraph_format.space_after = Pt(12)
        title._element.get_or_add_pPr().remove_all("w:pBdr")
        for index in range(1, 4):
            heading = document.styles[f"Heading {index}"]
            heading.font.color.rgb = RGBColor(0, 0, 0)
            heading.paragraph_format.keep_with_next = True
            heading.paragraph_format.space_before = Pt(12 if index == 1 else 8)
            heading.paragraph_format.space_after = Pt(6)
        body = document.styles["Body Text"]
        body.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        body.paragraph_format.first_line_indent = Pt(32)
        body.paragraph_format.line_spacing = Pt(28)
        body.paragraph_format.space_after = Pt(0)
        normal = document.styles["Normal"]
        normal.paragraph_format.line_spacing = Pt(28)
        normal.paragraph_format.space_after = Pt(0)

    @staticmethod
    def _set_run_font(run, font_name: str, size: float) -> None:
        run.font.name = font_name
        run.font.size = Pt(size)
        WordReportAuthor._set_rfonts(run._element.get_or_add_rPr(), font_name)

    @staticmethod
    def _set_rfonts(run_properties, font_name: str) -> None:
        fonts = run_properties.get_or_add_rFonts()
        for slot in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(qn(f"w:{slot}"), font_name)
        for slot in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
            fonts.attrib.pop(qn(f"w:{slot}"), None)

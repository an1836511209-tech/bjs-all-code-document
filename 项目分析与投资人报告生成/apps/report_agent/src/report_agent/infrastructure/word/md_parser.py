"""Parse report Markdown into ReportContent for Word generation.

The model writes a Markdown file in the workspace, using HTML comment markers
``<!-- cite: evidence_xxx -->`` to attach citations to paragraphs. This module
converts that Markdown into a :class:`ReportContent` that
:class:`WordReportAuthor` can render to DOCX.

The parser supports both inline and trailing citation styles:

- **Inline**: cite marker immediately after the content block
- **Trailing**: cite marker at the end of a section covering all preceding
  content blocks in the same section group (since the last ``##`` heading)

Markdown structure::

    # Report Title

    ## 一、Section heading (level 1)

    ### （一）Subsection (level 2)

    Paragraph text that may span multiple lines.

    More paragraph text.
    <!-- cite: evidence_abc123 -->

    - Bullet item text.
    <!-- cite: evidence_def456 -->

    | Header1 | Header2 |
    |---------|---------|
    | cell1   | cell2   |
    <!-- cite: evidence_ghi789 -->
"""

from __future__ import annotations

import re

from report_agent.domain.report_content import (
    EvidenceCitation,
    ReportContent,
    ReportSection,
    ReportStatus,
    ReportTable,
    ReportTableRow,
    ReportText,
    SrcMarker,
)

_CITE_PATTERN = re.compile(
    r"<!--\s*cite:\s*(evidence_[a-f0-9]{32})\s*-->", re.IGNORECASE
)
#: 写作时与正文一起落盘的来源标记：``<!-- src: <kind> <tool> <pointer> ; <note> -->``。
#: pointer 允许为空（例如 reasoned 推理只指向材料页），note 是最终批注文本。
_SRC_RE = re.compile(
    r"<!--\s*src:\s*(?P<kind>[A-Za-z_]+)"
    r"(?:\s+(?P<tool>[^\s;]+))?"
    r"(?:\s+(?P<pointer>[^\s;]+))?"
    r"\s*;\s*(?P<note>.*?)\s*-->",
    re.DOTALL,
)
_INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+)$")
_TABLE_ROW_PATTERN = re.compile(r"^\|(.+)\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\|[\s:|-]+\|\s*$")
_BULLET_PATTERN = re.compile(r"^\s*[-*]\s+(.+)$")
_NUMBERED_PATTERN = re.compile(r"^\s*\d+\.\s+(.+)$")


class MarkdownReportError(ValueError):
    """Raised when Markdown cannot be parsed into ReportContent."""


def parse_report_markdown(
    markdown: str,
    *,
    report_id: str,
    title: str,
    company_name: str,
    title_evidence_id: str,
) -> ReportContent:
    """Parse report Markdown into :class:`ReportContent`.

    See module docstring for the expected Markdown structure.
    """
    lines = markdown.splitlines()

    # Collect into intermediate mutable structures, then build frozen models
    # at the end to avoid frozen-model workarounds during parsing.
    sections_raw: list[dict] = []
    current: dict | None = None

    # Sections in the current group (since the last level-1 heading).
    # A cite marker at the end of a group applies to all uncited blocks
    # in all sections of that group.
    current_group: list[dict] = []

    # Table state
    table_headers: list[str] | None = None
    pending_table_rows: list[dict] = []
    table_id_counter = 0
    row_id_counter = 0

    # Paragraph state
    para_lines: list[str] = []

    def apply_citation(eid: str) -> None:
        """Apply a citation to all uncited blocks in the current group."""
        for section in current_group:
            for block in section["blocks"]:
                if block["type"] == "table":
                    for row in block["rows"]:
                        if not row["citations"]:
                            row["citations"].append(eid)
                elif not block["citations"]:
                    block["citations"].append(eid)
        # Also apply to pending (not-yet-flushed) table rows
        for row in pending_table_rows:
            if not row["citations"]:
                row["citations"].append(eid)

    def flush_paragraph() -> None:
        nonlocal para_lines
        if not para_lines or current is None:
            para_lines.clear()
            return
        raw = "\n".join(para_lines).strip()
        src = _extract_src_marker(raw)
        text = _strip_src_markers(raw)
        text = _strip_cite_markers(text)
        text = _strip_inline_markdown(text)
        if text:
            current["blocks"].append(
                {"type": "para", "text": text, "citations": [], "src": src,
                 "src_anchors": _src_anchors(raw)}
            )
        para_lines.clear()

    def flush_table() -> None:
        nonlocal table_headers, pending_table_rows, table_id_counter
        if table_headers is None or current is None:
            table_headers = None
            pending_table_rows = []
            return
        if pending_table_rows:
            table_id_counter += 1
            current["blocks"].append(
                {
                    "type": "table",
                    "table_id": f"md_table_{table_id_counter}",
                    "headers": list(table_headers),
                    "rows": pending_table_rows,
                }
            )
        table_headers = None
        pending_table_rows = []

    for line in lines:
        # Table separator
        if _TABLE_SEPARATOR.match(line):
            continue

        # Table row
        table_match = _TABLE_ROW_PATTERN.match(line)
        if table_match:
            cells = [c.strip() for c in table_match.group(1).split("|")]
            if table_headers is None:
                table_headers = cells
            else:
                flush_paragraph()
                row_id_counter += 1
                inline_cites = _extract_citation_ids(line)
                clean_cells = [_strip_cite_markers(c) for c in cells]
                clean_cells = [_strip_inline_markdown(c) for c in clean_cells]
                pending_table_rows.append(
                    {
                        "row_id": f"md_row_{row_id_counter}",
                        "values": clean_cells,
                        "citations": list(inline_cites),
                    }
                )
            continue

        # A citation comment between table rows belongs to the open table.
        # Flushing here would keep only the first data row and drop the rest.
        stripped = line.strip()
        cite_match = _CITE_PATTERN.match(stripped)
        if cite_match and table_headers is not None:
            apply_citation(cite_match.group(1))
            continue

        flush_table()

        # Heading
        heading_match = _HEADING_PATTERN.match(line)
        if heading_match:
            flush_paragraph()
            flush_table()
            level = len(heading_match.group(1))
            title_text = heading_match.group(2).strip()
            if level == 1:
                # Document title line - skip (title passed separately)
                continue
            current = {
                "section_id": _slug(title_text),
                "title": title_text,
                "heading_level": level - 1,  # ## = level 1, ### = level 2
                "blocks": [],
            }
            sections_raw.append(current)
            if level == 2:
                # Level-1 heading (##) starts a new section group
                current_group = [current]
            else:
                # Level-2 heading (###) joins the current group
                current_group.append(current)
            continue

        # Bullet (- or *)
        bullet_match = _BULLET_PATTERN.match(line)
        if bullet_match:
            flush_paragraph()
            if current is not None:
                raw = bullet_match.group(1).strip()
                src = _extract_src_marker(raw)
                text = _strip_src_markers(raw)
                text = _strip_cite_markers(text)
                text = _strip_inline_markdown(text)
                if text:
                    current["blocks"].append(
                        {"type": "bullet", "text": text, "citations": [], "src": src,
                         "src_anchors": _src_anchors(raw)}
                    )
            continue

        # Numbered list item (1. 2. etc.)
        numbered_match = _NUMBERED_PATTERN.match(line)
        if numbered_match:
            flush_paragraph()
            if current is not None:
                raw = numbered_match.group(1).strip()
                src = _extract_src_marker(raw)
                text = _strip_src_markers(raw)
                text = _strip_cite_markers(text)
                text = _strip_inline_markdown(text)
                if text:
                    current["blocks"].append(
                        {"type": "bullet", "text": text, "citations": [], "src": src,
                         "src_anchors": _src_anchors(raw)}
                    )
            continue

        # Cite-only line: apply citation to all uncited blocks in the group
        stripped = line.strip()
        cite_match = _CITE_PATTERN.match(stripped)
        if cite_match:
            eid = cite_match.group(1)
            apply_citation(eid)
            continue

        # Empty line = paragraph break
        if not stripped:
            flush_paragraph()
            continue

        # Regular text line - accumulate
        para_lines.append(line)

    # Final flush
    flush_paragraph()
    flush_table()

    if not sections_raw:
        raise MarkdownReportError("no sections found in markdown")

    # Build frozen ReportSection objects from intermediate dicts.
    # Paragraphs / bullets / table rows without citations are kept but
    # with empty citations tuple (still rendered, just no source link).
    sections = []
    for s in sections_raw:
        paragraphs = []
        bullet_items = []
        tables = []
        for block in s["blocks"]:
            if block["type"] == "para":
                paragraphs.append(
                    ReportText(
                        text=block["text"],
                        citations=tuple(
                            EvidenceCitation(evidence_id=eid)
                            for eid in block["citations"]
                        ),
                        src=_to_src_marker(block.get("src")),
                        src_anchors=tuple(block.get("src_anchors") or ()),
                    )
                )
            elif block["type"] == "bullet":
                bullet_items.append(
                    ReportText(
                        text=block["text"],
                        citations=tuple(
                            EvidenceCitation(evidence_id=eid)
                            for eid in block["citations"]
                        ),
                        src=_to_src_marker(block.get("src")),
                        src_anchors=tuple(block.get("src_anchors") or ()),
                    )
                )
            elif block["type"] == "table":
                rows = []
                for row in block["rows"]:
                    rows.append(
                        ReportTableRow(
                            row_id=row["row_id"],
                            values=tuple(row["values"]),
                            citations=tuple(
                                EvidenceCitation(evidence_id=eid)
                                for eid in row["citations"]
                            ),
                        )
                    )
                if rows:
                    tables.append(
                        ReportTable(
                            table_id=block["table_id"],
                            headers=tuple(block["headers"]),
                            rows=tuple(rows),
                        )
                    )
        sections.append(
            ReportSection(
                section_id=s["section_id"],
                title=s["title"],
                heading_level=s["heading_level"],
                paragraphs=tuple(paragraphs),
                bullet_items=tuple(bullet_items),
                tables=tuple(tables),
            )
        )

    return ReportContent(
        report_id=report_id,
        title=title,
        title_citations=(EvidenceCitation(evidence_id=title_evidence_id),),
        company_name=company_name,
        status=ReportStatus.DRAFT,
        sections=tuple(sections),
    )


def _extract_citation_ids(text: str) -> list[str]:
    """Extract unique evidence IDs from cite markers in text."""
    matches = _CITE_PATTERN.findall(text)
    seen: set[str] = set()
    unique: list[str] = []
    for eid in matches:
        if eid not in seen:
            seen.add(eid)
            unique.append(eid)
    return unique


def _strip_cite_markers(text: str) -> str:
    return _CITE_PATTERN.sub("", text).strip()


def _strip_inline_markdown(text: str) -> str:
    """Strip ``**bold**`` markers so literal ``**`` never leaks into Word output.

    Inline bold segments are dropped (markers removed). Mixed bold/text becomes
    plain. Authors should use ``### `` headings for true sub-section styling.
    """
    return _INLINE_BOLD.sub(r"\1", text).strip()


def _extract_src_marker(text: str) -> dict[str, str] | None:
    """Parse the first ``<!-- src: <kind> <tool> <pointer> ; <note> -->`` marker.

    Returns ``None`` when there is no marker, so legacy reports that only use
    ``<!-- cite: ... -->`` keep working unchanged.
    """
    match = _SRC_RE.search(text)
    if match is None:
        return None
    return {
        "kind": (match.group("kind") or "material").strip(),
        "tool": (match.group("tool") or "").strip(),
        "pointer": (match.group("pointer") or "").strip(),
        "note": (match.group("note") or "").strip(),
    }


def _src_anchors(raw: str) -> list[dict[str, object]]:
    """每个 src 标记 + 它的锚点句子，供渲染层按句生成批注。"""
    anchors: list[dict[str, object]] = []
    for marker in _extract_src_markers_with_anchor(raw):
        converted = _to_src_marker(marker)
        if converted is not None:
            anchors.append({"src": converted, "anchor": marker.get("anchor") or ""})
    return anchors


def _last_sentence(text: str) -> str:
    """取一段文字里最后一句（批注锚点用，越短越不容易匹配到别处）。"""
    cleaned = _strip_inline_markdown(_strip_cite_markers(_strip_src_markers(text))).strip()
    if not cleaned:
        return ""
    for part in reversed(re.split(r"(?<=[。！？；])", cleaned)):
        if part.strip():
            return part.strip()[:120]
    return cleaned[:120]


def _extract_src_markers_with_anchor(text: str) -> list[dict[str, str]]:
    """解析**全部** ``src`` 标记，并给每个标记配上它前面那句话。

    一个段落里常有多个来源：股权结构一条、子公司一条、资质一条。旧实现只取
    第一个标记，并拿**整段文字**当锚点，于是几条批注全挂到同一句上——客户看到的
    就是"同一段下面几条批注，页码和原文对不上"。

    锚点改成句子后，每条批注都能落到真正对应的事实上。
    """
    markers: list[dict[str, str]] = []
    position = 0
    last_anchor = ""
    for match in _SRC_RE.finditer(text):
        prefix = text[position : match.start()]
        position = match.end()
        anchor = _last_sentence(prefix)
        if not anchor:
            # 两个标记紧挨着（同一句话有两个来源）时，中间没有文字可当锚点，
            # 复用上一句——批注落在同一处是对的，落空才是错的。
            anchor = last_anchor
        if anchor:
            last_anchor = anchor
        markers.append(
            {
                "kind": (match.group("kind") or "material").strip(),
                "tool": (match.group("tool") or "").strip(),
                "pointer": (match.group("pointer") or "").strip(),
                "note": (match.group("note") or "").strip(),
                "anchor": anchor,
            }
        )
    return markers


def _strip_src_markers(text: str) -> str:
    return _SRC_RE.sub("", text).strip()


def _to_src_marker(raw: dict[str, str] | None) -> SrcMarker | None:
    """Convert the parsed marker dict into the domain model (``None`` if absent)."""
    if not raw:
        return None
    return SrcMarker(
        kind=raw.get("kind") or "material",
        tool=raw.get("tool") or "",
        pointer=raw.get("pointer") or "",
        note=raw.get("note") or "",
    )


def _slug(text: str) -> str:
    """Generate a section_id from heading text."""
    import hashlib

    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"sec_{digest}"

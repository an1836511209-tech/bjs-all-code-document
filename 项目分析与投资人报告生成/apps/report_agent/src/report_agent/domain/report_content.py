"""Simple report content with paragraph, item and row-level evidence citations."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReportStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    NEEDS_DATA = "needs_data"


class EvidenceCitation(BaseModel):
    """Traceability link from a report fact to a stored evidence record.

    Only ``evidence_id`` is stored — the model uses ``read_evidence`` /
    ``read_evidence_chunk`` to explore the evidence payload semantically,
    then writes the full comment text via ``add_report_comments``.
    No ``locator`` or ``source_summary`` is stored on the citation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(pattern=r"^evidence_[a-f0-9]{32}$")


class SrcMarker(BaseModel):
    """写作时与正文一起落盘的来源标记，直接渲染成 Word 批注。

    与 :class:`EvidenceCitation` 的分工：

    * ``EvidenceCitation`` 只记 ``evidence_id``，用于「这句话引用了哪条证据」；
    * ``SrcMarker`` 还记 ``pointer`` 和批注文本，让批注在**生成段落时**就能锚定，
      不必事后再用 ``match_text`` 子串匹配。

    语法（写在正文句末）::

        <!-- src: <kind> <tool> <pointer> ; <批注文本> -->
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(default="material", min_length=1)
    tool: str = ""
    pointer: str = ""
    note: str = ""


class ReportText(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    citations: tuple[EvidenceCitation, ...] = Field(default_factory=tuple)
    disclosure: str | None = None
    #: 随正文一起写入的来源标记，渲染时变成该段落的 Word 批注。
    src: SrcMarker | None = None
    #: 段落里每个 ``src`` 标记 + 它前面那句话。一个段落常有多个来源，按句子
    #: 锚定才能让每条批注落到对应的事实上（否则几条批注会挤在同一句上）。
    src_anchors: tuple[dict[str, Any], ...] = Field(default_factory=tuple)


class ReportTableRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    row_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    values: tuple[str, ...]
    citations: tuple[EvidenceCitation, ...] = Field(default_factory=tuple)
    cell_citations: dict[int, tuple[EvidenceCitation, ...]] = Field(default_factory=dict)
    disclosure: str | None = None


class ReportTable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    table_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    title: str | None = None
    headers: tuple[str, ...] = Field(min_length=1)
    rows: tuple[ReportTableRow, ...] = ()

    @model_validator(mode="after")
    def validate_rows(self) -> ReportTable:
        if any(len(row.values) != len(self.headers) for row in self.rows):
            raise ValueError("every table row must match the header width")
        if any(
            index < 0 or index >= len(self.headers)
            for row in self.rows
            for index in row.cell_citations
        ):
            raise ValueError("cell_citations index is outside the table width")
        return self


class ReportSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    section_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    title: str = Field(min_length=1)
    heading_level: Literal[1, 2, 3] = 1
    paragraphs: tuple[ReportText, ...] = ()
    bullet_items: tuple[ReportText, ...] = ()
    tables: tuple[ReportTable, ...] = ()


class MissingItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(pattern=r"^[A-Z0-9_]{1,64}$")
    description: str = Field(min_length=1)
    evidence_id: str | None = Field(default=None, pattern=r"^evidence_[a-f0-9]{32}$")


class ReportContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    title: str = Field(min_length=1)
    title_citations: tuple[EvidenceCitation, ...] = Field(min_length=1)
    company_name: str = Field(min_length=1)
    status: ReportStatus = ReportStatus.DRAFT
    sections: tuple[ReportSection, ...] = ()
    missing_items: tuple[MissingItem, ...] = ()

    @model_validator(mode="after")
    def validate_content(self) -> ReportContent:
        section_ids = [section.section_id for section in self.sections]
        row_ids = [
            row.row_id
            for section in self.sections
            for table in section.tables
            for row in table.rows
        ]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("section_id values must be unique")
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("row_id values must be unique")
        if self.status == ReportStatus.READY and not self.sections:
            raise ValueError("ready report content requires at least one section")
        return self

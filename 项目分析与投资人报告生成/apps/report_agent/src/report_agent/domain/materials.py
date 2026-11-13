"""Stable document-ingestion contract independent from parser libraries."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MaterialFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    PPTX = "pptx"
    PPT = "ppt"
    XLSX = "xlsx"
    XLS = "xls"
    CSV = "csv"


class PdfContentKind(StrEnum):
    DOCUMENT_SCAN = "document_scan"
    SLIDE_SCAN = "slide_scan"
    MIXED_OR_UNKNOWN = "mixed_or_unknown"


class RecognitionMethod(StrEnum):
    EMBEDDED_TEXT = "embedded_text"
    PADDLE_OCR = "paddle_ocr"
    MULTIMODAL = "multimodal"
    TIKA = "tika"


class MaterialLocator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int | None = Field(default=None, ge=1)
    slide: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    cell_range: str | None = None
    paragraph: int | None = Field(default=None, ge=1)


class MaterialBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    block_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,160}$")
    kind: str = Field(pattern=r"^[a-z_]{1,32}$")
    text: str = ""
    locator: MaterialLocator
    recognition_method: RecognitionMethod = RecognitionMethod.EMBEDDED_TEXT
    confidence: float | None = Field(default=None, ge=0, le=1)
    #: True when the page encodes meaning in shapes rather than words — a
    #: progress matrix, a dot grid, a flowchart. Text extraction cannot recover
    #: those states, so anything read from such a page needs a qualifier.
    chart_heavy: bool = False


class PageImage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int = Field(ge=1)
    path: Path
    media_type: str = Field(pattern=r"^image/(png|jpeg)$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ParsedMaterial(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    material_id: str = Field(pattern=r"^material_[a-f0-9]{32}$")
    source_name: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    format: MaterialFormat
    blocks: tuple[MaterialBlock, ...] = ()
    page_images: tuple[PageImage, ...] = ()
    pdf_kind: PdfContentKind | None = None
    warnings: tuple[str, ...] = ()
    requires_visual_classification: bool = False

    @model_validator(mode="after")
    def pdf_kind_only_applies_to_pdf(self) -> ParsedMaterial:
        if self.format != MaterialFormat.PDF and self.pdf_kind is not None:
            raise ValueError("pdf_kind is only valid for PDF materials")
        return self

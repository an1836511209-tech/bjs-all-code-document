"""Deterministic extraction and recognition for trusted task inputs."""

from __future__ import annotations

import csv
import hashlib
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pymupdf
import xlrd  # type: ignore[import-untyped]
from openpyxl import load_workbook  # type: ignore[import-untyped]

from report_agent.domain.materials import (
    MaterialBlock,
    MaterialFormat,
    MaterialLocator,
    PageImage,
    ParsedMaterial,
    PdfContentKind,
    RecognitionMethod,
)
from report_agent.infrastructure.materials.conversion import (
    GotenbergConverter,
    TikaTextExtractor,
)
from report_agent.infrastructure.materials.detection import detect_material_format
from report_agent.application.recognition import PageRecognition
from report_agent.infrastructure.materials.http_recognition import (
    OpenAICompatibleVisionAdapter,
    PaddleLayoutAdapter,
)

logger = logging.getLogger(__name__)

# Diagnostic threshold for the middle-page character median. Below this the
# PDF likely is a scan; it is recorded as a warning but does not change routing
# (aspect ratio is the routing signal).
LOW_TEXT_DIAGNOSTIC = 200

#: A page whose vector graphics outnumber its words is a chart page. The
#: states it encodes — a progress matrix of filled/hollow/grey dots, a
#: milestone flowchart — exist only as shapes, so neither a text extractor nor
#: a layout parser can recover them. Below this many drawings a page is
#: ordinary decoration and is not flagged.
CHART_ELEMENT_THRESHOLD = 40

#: Pages with at least this many characters of text are document-like even if
#: they carry many drawings (tables, annotated forms).
CHART_TEXT_CEILING = 400


def _chart_pages(pdf_path: Path) -> set[int]:
    """Return the 1-based page numbers whose meaning lives in shapes."""
    try:
        with pymupdf.open(pdf_path) as document:
            pages: set[int] = set()
            for index in range(document.page_count):
                page = document[index]
                try:
                    drawings = page.get_drawings()
                except Exception:  # noqa: BLE001 - a broken page must not fail the parse
                    continue
                if len(drawings) < CHART_ELEMENT_THRESHOLD:
                    continue
                if len(page.get_text("text").strip()) > CHART_TEXT_CEILING:
                    continue
                pages.add(index + 1)
            return pages
    except Exception:  # noqa: BLE001 - chart detection is best effort
        logger.warning("chart page detection failed for %s", pdf_path, exc_info=True)
        return set()


class MaterialParser:
    """Parse trusted task inputs, routing each format to the right pipeline.

    DOCX/DOC -> Apache Tika text extraction.
    PPT/PPTX -> Gotenberg to PDF -> multimodal per-page recognition.
    PDF      -> aspect-ratio classify -> slide (multimodal) or document (PaddleOCR).
    XLSX/XLS/CSV -> embedded extraction (unchanged).
    """

    def __init__(
        self,
        *,
        gotenberg: GotenbergConverter,
        tika: TikaTextExtractor,
        paddle: PaddleLayoutAdapter,
        vision: OpenAICompatibleVisionAdapter,
        vision_concurrency: int = 4,
    ) -> None:
        self.gotenberg = gotenberg
        self.tika = tika
        self.paddle = paddle
        self.vision = vision
        self._vision_concurrency = max(1, vision_concurrency)

    def parse(self, source: Path, preview_dir: Path | None = None) -> ParsedMaterial:
        source = source.resolve(strict=True)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        material_id = f"material_{uuid.uuid4().hex}"
        material_format = detect_material_format(source)
        blocks: list[MaterialBlock]
        images: tuple[PageImage, ...] = ()
        pdf_kind: PdfContentKind | None = None
        warnings: list[str] = []
        requires_visual_classification = False

        if material_format in (MaterialFormat.DOCX, MaterialFormat.DOC):
            blocks = self._tika(source)
        elif material_format in (MaterialFormat.PPTX, MaterialFormat.PPT):
            pdf_path = self._convert_to_pdf(source, preview_dir)
            blocks, images = self._recognize_slide(pdf_path, preview_dir)
            requires_visual_classification = True
        elif material_format == MaterialFormat.XLSX:
            blocks = self._xlsx(source)
        elif material_format == MaterialFormat.XLS:
            blocks = self._xls(source)
        elif material_format == MaterialFormat.CSV:
            blocks = self._csv(source)
        elif material_format == MaterialFormat.PDF:
            pdf_kind = self._classify_pdf(source)
            chart_pages = _chart_pages(source)
            if pdf_kind == PdfContentKind.SLIDE_SCAN:
                blocks, images = self._recognize_slide(source, preview_dir)
                requires_visual_classification = True
            elif pdf_kind == PdfContentKind.DOCUMENT_SCAN:
                blocks = self._recognize_document(source)
            else:
                # Empty or unrecognizable PDF: nothing to extract.
                blocks = []
                warnings.append("PDF has no pages or could not be classified")
            if chart_pages:
                blocks = [
                    block.model_copy(update={"chart_heavy": True})
                    if block.locator.page in chart_pages
                    else block
                    for block in blocks
                ]
                warnings.append(
                    "pages "
                    + ", ".join(str(page) for page in sorted(chart_pages))
                    + " encode charts: states drawn as shapes are not recoverable "
                    "from the text layer and must be qualified in the report"
                )
        else:
            raise ValueError(f"unsupported material format: {material_format.value}")

        return ParsedMaterial(
            material_id=material_id,
            source_name=source.name,
            source_sha256=digest,
            format=material_format,
            blocks=tuple(blocks),
            page_images=images,
            pdf_kind=pdf_kind,
            warnings=tuple(warnings),
            requires_visual_classification=requires_visual_classification,
        )

    # ------------------------------------------------------------------ PDF

    def _classify_pdf(self, source: Path) -> PdfContentKind:
        """Classify a PDF by page aspect ratio.

        Landscape pages (width > height) indicate a slide-derived PDF;
        portrait pages indicate a document PDF. The middle-page character
        median is recorded as a diagnostic warning when low.
        """
        with pymupdf.open(source) as document:
            page_count = document.page_count
            if page_count == 0:
                return PdfContentKind.MIXED_OR_UNKNOWN
            landscape = 0
            middle_chars: list[int] = []
            indices = self._middle_page_indices(page_count)
            for index in range(page_count):
                page = document[index]
                rect = page.rect
                if rect.width > rect.height:
                    landscape += 1
                if index in indices:
                    middle_chars.append(len(page.get_text("text").strip()))
        ratio = landscape / page_count
        if middle_chars:
            middle_chars.sort()
            median = middle_chars[len(middle_chars) // 2]
            if median < LOW_TEXT_DIAGNOSTIC:
                logger.info(
                    "PDF %s middle-page char median=%d below diagnostic %d",
                    source.name,
                    median,
                    LOW_TEXT_DIAGNOSTIC,
                )
        return PdfContentKind.SLIDE_SCAN if ratio >= 0.5 else PdfContentKind.DOCUMENT_SCAN

    @staticmethod
    def _middle_page_indices(page_count: int) -> set[int]:
        if page_count <= 3:
            return set(range(page_count))
        mid = page_count // 2
        return {mid - 1, mid, mid + 1}

    def _recognize_slide(
        self, pdf_path: Path, preview_dir: Path | None
    ) -> tuple[list[MaterialBlock], tuple[PageImage, ...]]:
        if preview_dir is None:
            raise ValueError("slide recognition requires a preview directory")
        images = self.render_all_pages(pdf_path, preview_dir)
        blocks: list[MaterialBlock] = []
        # Concurrent multimodal recognition: submit all pages to a thread
        # pool, collect results keyed by page number, then assemble blocks in
        # page order so output stays deterministic.
        results: dict[int, PageRecognition] = {}
        with ThreadPoolExecutor(max_workers=self._vision_concurrency) as pool:
            future_to_page = {
                pool.submit(self.vision.recognize, image): image.page
                for image in images
            }
            for future in as_completed(future_to_page):
                page = future_to_page[future]
                try:
                    results[page] = future.result()
                except Exception:
                    logger.exception("vision recognition failed for page %d", page)
        for image in images:
            recognition = results.get(image.page)
            if recognition is None or not recognition.text.strip():
                continue
            blocks.append(
                MaterialBlock(
                    block_id=f"page.{image.page}",
                    kind="page",
                    text=recognition.text.strip(),
                    locator=MaterialLocator(page=image.page),
                    recognition_method=RecognitionMethod.MULTIMODAL,
                    confidence=recognition.confidence,
                )
            )
        return blocks, images

    def _recognize_document(self, pdf_path: Path) -> list[MaterialBlock]:
        recognitions = self.paddle.recognize_pdf(pdf_path)
        blocks: list[MaterialBlock] = []
        for page_number, recognition in enumerate(recognitions, 1):
            if not recognition.text.strip():
                continue
            blocks.append(
                MaterialBlock(
                    block_id=f"page.{page_number}",
                    kind="page",
                    text=recognition.text.strip(),
                    locator=MaterialLocator(page=page_number),
                    recognition_method=RecognitionMethod.PADDLE_OCR,
                    confidence=recognition.confidence,
                )
            )
        return blocks

    # ------------------------------------------------------------- rendering

    @staticmethod
    def render_all_pages(source: Path, output_dir: Path) -> tuple[PageImage, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        rendered: list[PageImage] = []
        with pymupdf.open(source) as document:
            for index in range(document.page_count):
                pixmap = document[index].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                data = pixmap.tobytes("png")
                target = output_dir / f"page-{index + 1}.png"
                target.write_bytes(data)
                rendered.append(
                    PageImage(
                        page=index + 1,
                        path=target.resolve(),
                        media_type="image/png",
                        width=pixmap.width,
                        height=pixmap.height,
                        sha256=hashlib.sha256(data).hexdigest(),
                    )
                )
        return tuple(rendered)

    # ----------------------------------------------------------- conversion

    def _convert_to_pdf(self, source: Path, preview_dir: Path | None) -> Path:
        output_dir = (preview_dir or source.parent) / "converted"
        return self.gotenberg.to_pdf(source, output_dir)

    # --------------------------------------------------------------- Tika

    def _tika(self, source: Path) -> list[MaterialBlock]:
        text = self.tika.extract(source)
        blocks: list[MaterialBlock] = []
        paragraph_index = 0
        for chunk in re.split(r"\n\s*\n", text):
            cleaned = chunk.strip()
            if not cleaned:
                continue
            paragraph_index += 1
            blocks.append(
                MaterialBlock(
                    block_id=f"p.{paragraph_index}",
                    kind="paragraph",
                    text=cleaned,
                    locator=MaterialLocator(paragraph=paragraph_index),
                    recognition_method=RecognitionMethod.TIKA,
                )
            )
        return blocks

    # ------------------------------------------------------------- spreadsheets

    @staticmethod
    def _xlsx(source: Path) -> list[MaterialBlock]:
        workbook = load_workbook(source, read_only=True, data_only=True)
        blocks: list[MaterialBlock] = []
        try:
            for sheet in workbook.worksheets:
                rows = [
                    ["" if value is None else str(value) for value in row]
                    for row in sheet.iter_rows(values_only=True)
                ]
                while rows and not any(rows[-1]):
                    rows.pop()
                if rows:
                    width = max(len(row) for row in rows)
                    end = f"{_excel_column(width)}{len(rows)}"
                    blocks.append(
                        MaterialBlock(
                            block_id=f"sheet.{_safe_id(sheet.title)}",
                            kind="sheet",
                            text="\n".join("\t".join(row) for row in rows),
                            locator=MaterialLocator(sheet=sheet.title, cell_range=f"A1:{end}"),
                        )
                    )
        finally:
            workbook.close()
        return blocks

    @staticmethod
    def _xls(source: Path) -> list[MaterialBlock]:
        workbook = xlrd.open_workbook(source, on_demand=True)
        blocks: list[MaterialBlock] = []
        try:
            for sheet in workbook.sheets():
                rows = [
                    [str(sheet.cell_value(row, column)) for column in range(sheet.ncols)]
                    for row in range(sheet.nrows)
                ]
                if rows:
                    blocks.append(
                        MaterialBlock(
                            block_id=f"sheet.{_safe_id(sheet.name)}",
                            kind="sheet",
                            text="\n".join("\t".join(row) for row in rows),
                            locator=MaterialLocator(
                                sheet=sheet.name,
                                cell_range=f"A1:{_excel_column(sheet.ncols)}{sheet.nrows}",
                            ),
                        )
                    )
        finally:
            workbook.release_resources()
        return blocks

    @staticmethod
    def _csv(source: Path) -> list[MaterialBlock]:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        text = "\n".join("\t".join(row) for row in rows)
        return (
            [
                MaterialBlock(
                    block_id="sheet.csv",
                    kind="sheet",
                    text=text,
                    locator=MaterialLocator(sheet="CSV"),
                )
            ]
            if rows
            else []
        )


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return normalized[:120] or "unnamed"


def _excel_column(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result or "A"

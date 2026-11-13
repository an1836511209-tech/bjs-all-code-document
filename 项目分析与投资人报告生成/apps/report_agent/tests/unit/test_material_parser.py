"""Unit tests for the reworked material parser and its adapters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from report_agent.domain.materials import (
    MaterialFormat,
    PageImage,
    PdfContentKind,
    RecognitionMethod,
)
from report_agent.infrastructure.materials.http_recognition import (
    OpenAICompatibleVisionAdapter,
    PaddleLayoutAdapter,
    _find_text,
)
from report_agent.infrastructure.materials.parser import MaterialParser

# ----------------------------------------------------------------- helpers


def _make_parser(
    *,
    gotenberg=None,
    tika=None,
    paddle=None,
    vision=None,
) -> MaterialParser:
    return MaterialParser(
        gotenberg=gotenberg or MagicMock(),
        tika=tika or MagicMock(),
        paddle=paddle or MagicMock(),
        vision=vision or MagicMock(),
    )


class _FakeRect:
    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height


class _FakePage:
    def __init__(self, rect: _FakeRect, text: str = "") -> None:
        self.rect = rect
        self._text = text

    def get_text(self, *_args, **_kwargs) -> str:
        return self._text


class _FakeDocument:
    def __init__(self, pages: list[_FakePage]) -> None:
        self._pages = pages
        self.page_count = len(pages)

    def __enter__(self) -> _FakeDocument:
        return self

    def __exit__(self, *_args) -> None:
        return None

    def __getitem__(self, index: int) -> _FakePage:
        return self._pages[index]


# --------------------------------------------------------- _classify_pdf


def test_classify_pdf_landscape_majority_is_slide(tmp_path: Path) -> None:
    pdf = tmp_path / "slide.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    pages = [
        _FakePage(_FakeRect(960, 540)),  # landscape
        _FakePage(_FakeRect(960, 540)),
        _FakePage(_FakeRect(595, 842)),  # portrait
    ]
    parser = _make_parser()
    with patch("report_agent.infrastructure.materials.parser.pymupdf.open", return_value=_FakeDocument(pages)):
        kind = parser._classify_pdf(pdf)
    assert kind == PdfContentKind.SLIDE_SCAN


def test_classify_pdf_portrait_majority_is_document(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    pages = [
        _FakePage(_FakeRect(595, 842)),
        _FakePage(_FakeRect(595, 842)),
        _FakePage(_FakeRect(960, 540)),
    ]
    parser = _make_parser()
    with patch("report_agent.infrastructure.materials.parser.pymupdf.open", return_value=_FakeDocument(pages)):
        kind = parser._classify_pdf(pdf)
    assert kind == PdfContentKind.DOCUMENT_SCAN


def test_classify_pdf_zero_pages_is_mixed(tmp_path: Path) -> None:
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    parser = _make_parser()
    with patch("report_agent.infrastructure.materials.parser.pymupdf.open", return_value=_FakeDocument([])):
        kind = parser._classify_pdf(pdf)
    assert kind == PdfContentKind.MIXED_OR_UNKNOWN


# --------------------------------------------------------- _recognize_document


def test_paddle_layout_adapter_extracts_per_page_markdown() -> None:
    payload = {
        "logId": "x",
        "errorCode": 0,
        "result": {
            "layoutParsingResults": [
                {"markdown": {"text": "# Page 1\n\ncontent one"}},
                {"markdown": {"text": "page two text"}},
            ],
            "dataInfo": {},
        },
    }
    results = PaddleLayoutAdapter._extract_page_markdowns(payload)
    assert [r.text for r in results] == ["# Page 1\n\ncontent one", "page two text"]


def test_paddle_layout_adapter_falls_back_to_single_text() -> None:
    payload = {"result": {"markdown": {"text": "whole doc"}}}
    results = PaddleLayoutAdapter._extract_page_markdowns(payload)
    assert len(results) == 1
    assert results[0].text == "whole doc"


def test_paddle_layout_adapter_empty_returns_nothing() -> None:
    assert PaddleLayoutAdapter._extract_page_markdowns({}) == []


def test_paddle_layout_adapter_posts_json_base64_body(tmp_path: Path) -> None:
    """layout-parsing-vl rejects multipart; it expects JSON file + fileType."""
    import base64
    import json

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 teaser-bytes")
    adapter = PaddleLayoutAdapter(
        endpoint="http://ocr.example/layout-parsing-vl",
        token="tok",
        timeout_seconds=5,
    )
    response = MagicMock()
    response.json.return_value = {
        "result": {"layoutParsingResults": [{"markdown": {"text": "page one"}}]}
    }
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.post.return_value = response
    client.__enter__.return_value = client
    client.__exit__.return_value = False

    with patch(
        "report_agent.infrastructure.materials.http_recognition.httpx.Client",
        return_value=client,
    ):
        pages = adapter.recognize_pdf(pdf)

    assert [page.text for page in pages] == ["page one"]
    assert client.post.call_count == 1
    args, kwargs = client.post.call_args
    assert args[0] == "http://ocr.example/layout-parsing-vl"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert "files" not in kwargs
    assert "data" not in kwargs
    body = json.loads(kwargs["content"])
    assert body["fileType"] == 0
    assert body["file"] == base64.b64encode(b"%PDF-1.4 teaser-bytes").decode("ascii")
    assert body["useLayoutDetection"] is True


def test_find_text_recurses_into_nested_structures() -> None:
    assert _find_text({"a": {"text": "deep"}}) == "deep"
    assert _find_text({"items": [{"content": "x"}, {"content": "y"}]}) == "x\ny"


# --------------------------------------------------------- vision adapter


def test_vision_adapter_parses_chunk_json() -> None:
    adapter = OpenAICompatibleVisionAdapter(
        base_url="http://x", api_key="k", model="m", max_retries=1
    )
    content = '```json\n{"chunks":[{"layout":"mixed","text":"整页内容"}]}\n```'
    assert adapter._parse_chunk_text(content) == "整页内容"


def test_vision_adapter_returns_none_on_garbage() -> None:
    adapter = OpenAICompatibleVisionAdapter(
        base_url="http://x", api_key="k", model="m", max_retries=1
    )
    assert adapter._parse_chunk_text("no json here") is None
    assert adapter._parse_chunk_text("") is None


# --------------------------------------------------------- parser routing


def test_parse_pdf_document_routes_to_paddle(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    pages = [_FakePage(_FakeRect(595, 842), text="x" * 300)]
    paddle = MagicMock()
    paddle.recognize_pdf.return_value = [
        MagicMock(text="page one markdown", confidence=0.9),
    ]
    parser = _make_parser(paddle=paddle)
    with patch("report_agent.infrastructure.materials.parser.pymupdf.open", return_value=_FakeDocument(pages)):
        parsed = parser.parse(pdf, tmp_path / "preview")
    assert parsed.format == MaterialFormat.PDF
    assert parsed.pdf_kind == PdfContentKind.DOCUMENT_SCAN
    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].recognition_method == RecognitionMethod.PADDLE_OCR
    assert parsed.blocks[0].text == "page one markdown"
    assert parsed.requires_visual_classification is False


def test_parse_docx_routes_to_tika(tmp_path: Path) -> None:
    docx = tmp_path / "note.docx"
    docx.write_bytes(b"placeholder")
    tika = MagicMock()
    tika.extract.return_value = "标题段落\n\n第二段内容\n\n\n第三段"
    parser = _make_parser(tika=tika)
    with patch(
        "report_agent.infrastructure.materials.parser.detect_material_format",
        return_value=MaterialFormat.DOCX,
    ):
        parsed = parser.parse(docx)
    assert parsed.format == MaterialFormat.DOCX
    assert [b.text for b in parsed.blocks] == ["标题段落", "第二段内容", "第三段"]
    assert all(b.recognition_method == RecognitionMethod.TIKA for b in parsed.blocks)
    assert [b.block_id for b in parsed.blocks] == ["p.1", "p.2", "p.3"]


def test_parse_pptx_routes_through_gotenberg_to_slide(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"placeholder")
    converted_pdf = tmp_path / "converted" / "deck.pdf"
    converted_pdf.parent.mkdir(parents=True, exist_ok=True)
    converted_pdf.write_bytes(b"%PDF-1.4 fake")
    gotenberg = MagicMock()
    gotenberg.to_pdf.return_value = converted_pdf
    vision = MagicMock()
    vision.recognize.return_value = MagicMock(text="slide text", confidence=0.8)
    parser = _make_parser(gotenberg=gotenberg, vision=vision)
    png = tmp_path / "page-1.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_image = PageImage(
        page=1,
        path=png,
        media_type="image/png",
        width=960,
        height=540,
        sha256="a" * 64,
    )
    with patch(
        "report_agent.infrastructure.materials.parser.detect_material_format",
        return_value=MaterialFormat.PPTX,
    ), patch.object(
        MaterialParser, "render_all_pages", return_value=(fake_image,)
    ):
        parsed = parser.parse(pptx, tmp_path / "preview")
    assert parsed.format == MaterialFormat.PPTX
    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].recognition_method == RecognitionMethod.MULTIMODAL
    assert parsed.requires_visual_classification is True
    gotenberg.to_pdf.assert_called_once()


def test_parse_empty_pdf_returns_no_blocks_with_warning(tmp_path: Path) -> None:
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    parser = _make_parser()
    with patch("report_agent.infrastructure.materials.parser.pymupdf.open", return_value=_FakeDocument([])):
        parsed = parser.parse(pdf, tmp_path / "preview")
    assert parsed.pdf_kind == PdfContentKind.MIXED_OR_UNKNOWN
    assert parsed.blocks == ()
    assert parsed.warnings


# ----------------------------------------------- missing routing coverage


def test_parse_pdf_slide_routes_to_multimodal(tmp_path: Path) -> None:
    """Landscape-majority PDF should route to vision recognition end-to-end."""
    pdf = tmp_path / "slide.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    pages = [
        _FakePage(_FakeRect(960, 540), text="slide text"),
        _FakePage(_FakeRect(960, 540), text="more slide"),
    ]
    vision = MagicMock()
    vision.recognize.return_value = MagicMock(text="recognized slide", confidence=0.85)
    paddle = MagicMock()
    parser = _make_parser(paddle=paddle, vision=vision)
    png = tmp_path / "page-1.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_image = PageImage(
        page=1, path=png, media_type="image/png",
        width=960, height=540, sha256="b" * 64,
    )
    with patch("report_agent.infrastructure.materials.parser.pymupdf.open", return_value=_FakeDocument(pages)), \
         patch.object(MaterialParser, "render_all_pages", return_value=(fake_image, fake_image)):
        parsed = parser.parse(pdf, tmp_path / "preview")
    assert parsed.pdf_kind == PdfContentKind.SLIDE_SCAN
    assert parsed.requires_visual_classification is True
    assert all(b.recognition_method == RecognitionMethod.MULTIMODAL for b in parsed.blocks)
    paddle.recognize_pdf.assert_not_called()
    vision.recognize.assert_called()


def test_parse_doc_routes_to_tika(tmp_path: Path) -> None:
    """Legacy .doc should route through Tika just like .docx."""
    doc = tmp_path / "legacy.doc"
    doc.write_bytes(b"placeholder")
    tika = MagicMock()
    tika.extract.return_value = "DOC content\n\nsecond para"
    parser = _make_parser(tika=tika)
    with patch(
        "report_agent.infrastructure.materials.parser.detect_material_format",
        return_value=MaterialFormat.DOC,
    ):
        parsed = parser.parse(doc)
    assert parsed.format == MaterialFormat.DOC
    assert [b.text for b in parsed.blocks] == ["DOC content", "second para"]
    assert all(b.recognition_method == RecognitionMethod.TIKA for b in parsed.blocks)


def test_parse_ppt_routes_through_gotenberg_to_slide(tmp_path: Path) -> None:
    """Legacy .ppt should route through Gotenberg → multimodal like .pptx."""
    ppt = tmp_path / "legacy.ppt"
    ppt.write_bytes(b"placeholder")
    converted_pdf = tmp_path / "converted" / "legacy.pdf"
    converted_pdf.parent.mkdir(parents=True, exist_ok=True)
    converted_pdf.write_bytes(b"%PDF-1.4 fake")
    gotenberg = MagicMock()
    gotenberg.to_pdf.return_value = converted_pdf
    vision = MagicMock()
    vision.recognize.return_value = MagicMock(text="ppt slide", confidence=0.8)
    parser = _make_parser(gotenberg=gotenberg, vision=vision)
    png = tmp_path / "page-1.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_image = PageImage(
        page=1, path=png, media_type="image/png",
        width=960, height=540, sha256="c" * 64,
    )
    with patch(
        "report_agent.infrastructure.materials.parser.detect_material_format",
        return_value=MaterialFormat.PPT,
    ), patch.object(
        MaterialParser, "render_all_pages", return_value=(fake_image,)
    ):
        parsed = parser.parse(ppt, tmp_path / "preview")
    assert parsed.format == MaterialFormat.PPT
    assert parsed.blocks[0].recognition_method == RecognitionMethod.MULTIMODAL
    assert parsed.requires_visual_classification is True
    gotenberg.to_pdf.assert_called_once()


def test_parse_xlsx_routes_to_embedded_extraction(tmp_path: Path) -> None:
    """XLSX should use openpyxl embedded extraction, no external service."""
    xlsx = tmp_path / "data.xlsx"
    # Write a minimal real xlsx via openpyxl
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["A1", "B1"])
    ws.append(["A2", "B2"])
    wb.save(xlsx)
    parser = _make_parser()
    parsed = parser.parse(xlsx)
    assert parsed.format == MaterialFormat.XLSX
    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].kind == "sheet"
    assert parsed.blocks[0].recognition_method == RecognitionMethod.EMBEDDED_TEXT
    assert "A1\tB1" in parsed.blocks[0].text
    assert "A2\tB2" in parsed.blocks[0].text


def test_parse_xls_routes_to_embedded_extraction(tmp_path: Path) -> None:
    """Legacy .xls should route to xlrd embedded extraction."""
    xls = tmp_path / "legacy.xls"
    xls.write_bytes(b"placeholder")
    parser = _make_parser()
    fake_sheet = MagicMock()
    fake_sheet.name = "Sheet1"
    fake_sheet.nrows = 2
    fake_sheet.ncols = 2
    fake_sheet.cell_value = MagicMock(side_effect=lambda r, c: [["A1", "B1"], ["A2", "B2"]][r][c])
    fake_workbook = MagicMock()
    fake_workbook.sheets.return_value = [fake_sheet]
    fake_workbook.release_resources = MagicMock()
    with patch(
        "report_agent.infrastructure.materials.parser.detect_material_format",
        return_value=MaterialFormat.XLS,
    ), patch(
        "report_agent.infrastructure.materials.parser.xlrd.open_workbook",
        return_value=fake_workbook,
    ):
        parsed = parser.parse(xls)
    assert parsed.format == MaterialFormat.XLS
    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].kind == "sheet"
    assert parsed.blocks[0].recognition_method == RecognitionMethod.EMBEDDED_TEXT
    assert "A1\tB1" in parsed.blocks[0].text
    assert "A2\tB2" in parsed.blocks[0].text


def test_parse_csv_routes_to_embedded_extraction(tmp_path: Path) -> None:
    """CSV should be read directly as a single sheet block."""
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("col1,col2\nval1,val2\n", encoding="utf-8")
    parser = _make_parser()
    parsed = parser.parse(csv_file)
    assert parsed.format == MaterialFormat.CSV
    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].kind == "sheet"
    assert parsed.blocks[0].recognition_method == RecognitionMethod.EMBEDDED_TEXT
    assert "col1\tcol2" in parsed.blocks[0].text
    assert "val1\tval2" in parsed.blocks[0].text


def test_classify_pdf_50_50_boundary_is_slide(tmp_path: Path) -> None:
    """When landscape ratio is exactly 50%, the >= 0.5 threshold should classify as slide."""
    pdf = tmp_path / "mixed.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    pages = [
        _FakePage(_FakeRect(960, 540)),   # landscape
        _FakePage(_FakeRect(595, 842)),   # portrait
    ]
    parser = _make_parser()
    with patch("report_agent.infrastructure.materials.parser.pymupdf.open", return_value=_FakeDocument(pages)):
        kind = parser._classify_pdf(pdf)
    assert kind == PdfContentKind.SLIDE_SCAN

#!/usr/bin/env python3
"""Verify which rotation angle aligns bboxes with Paddle OCR coords."""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.paddle_pdf_highlighter import PaddlePDFHighlighter, clear_pdf_cache

PDF = Path(
    r"C:\Users\an183\Desktop\文件资料\项目档案\大宗\央企实物3-2\央企三部-于浒-GR2022BJ1002368-2\2.pdf"
)
OCR_JSON = ROOT / "logs/paddle_reproduce/20260604_161325/ocr_vl_response.json"
OUT = OCR_JSON.parent / "rotation_verify"
OUT.mkdir(parents=True, exist_ok=True)

data = json.loads(OCR_JSON.read_text(encoding="utf-8"))
pages = data["result"]["layoutParsingResults"]
pdf_bytes = PDF.read_bytes()

lines = []
for page_idx in [0, 1, 3]:
    page = pages[page_idx]
    ocr_angle = (page.get("prunedResult", {}).get("doc_preprocessor_res") or {}).get("angle", 0)
    blocks = [b for b in page["prunedResult"]["parsing_res_list"] if b.get("block_content", "").strip()]
    if not blocks:
        continue
    bbox = blocks[0]["block_bbox"]
    text = blocks[0]["block_content"][:40]
    lines.append(f"page_idx={page_idx} ocr_angle={ocr_angle} bbox={bbox} text={text!r}")

    url = page.get("inputImage")
    if url:
        try:
            img = urllib.request.urlopen(url, timeout=60).read()
            (OUT / f"page{page_idx}_inputImage.jpg").write_bytes(img)
            lines.append(f"  saved inputImage ({len(img)} bytes)")
        except Exception as e:
            lines.append(f"  inputImage download failed: {e}")

    for rot in (0, ocr_angle):
        clear_pdf_cache()
        img_bytes = PaddlePDFHighlighter.generate_highlight_image(
            pdf_bytes,
            page_idx,
            [bbox],
            rotation_angle=rot,
            use_cache=False,
            output_format="PNG",
        )
        if img_bytes:
            name = f"page{page_idx}_apply_rot{rot}.png"
            (OUT / name).write_bytes(img_bytes)
            lines.append(f"  saved {name}")

(OUT / "report.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))

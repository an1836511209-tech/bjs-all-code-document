#!/usr/bin/env python3
"""Debug PDF/OCR rotation for a file."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from src.utils.paddle_pdf_highlighter import PaddlePDFHighlighter, clear_pdf_cache


def main():
    pdf_path = Path(
        r"C:\Users\an183\Desktop\文件资料\项目档案\大宗\央企实物3-2\央企三部-于浒-GR2022BJ1002368-2\2.pdf"
    )
    ocr_json = ROOT / "logs/paddle_reproduce/20260604_161325/ocr_vl_response.json"

    doc = fitz.open(str(pdf_path))
    print(f"PDF pages: {doc.page_count}")
    for i in range(doc.page_count):
        p = doc[i]
        print(
            f"  page_idx={i} ui_page={i + 1} "
            f"pdf_rotation={p.rotation} rect={p.rect.width:.0f}x{p.rect.height:.0f}"
        )
    doc.close()

    if ocr_json.is_file():
        data = json.loads(ocr_json.read_text(encoding="utf-8"))
        pages = data["result"]["layoutParsingResults"]
        print(f"\nOCR pages: {len(pages)}")
        for i, page in enumerate(pages):
            pr = page.get("prunedResult", {})
            dpr = pr.get("doc_preprocessor_res") or {}
            angle = dpr.get("angle", 0)
            print(f"  page_idx={i} ui_page={i + 1} ocr_angle={angle}")

    # render page 0 and 1 with rotation 0 for visual check
    out = ROOT / "logs/paddle_reproduce/20260604_161325/highlight_test"
    out.mkdir(parents=True, exist_ok=True)
    pdf_bytes = pdf_path.read_bytes()
    ocr_angles = [0, 0, 0, 180, 180, 0, 0, 180, 0, 0]
    for idx in range(min(4, len(ocr_angles))):
        for rot in (0, ocr_angles[idx]):
            clear_pdf_cache()
            img_bytes = PaddlePDFHighlighter.generate_highlight_image(
                pdf_bytes,
                idx,
                [[50, 50, 200, 120]],
                rotation_angle=rot,
                use_cache=False,
                output_format="PNG",
            )
            if img_bytes:
                name = f"page{idx}_ocr{ocr_angles[idx]}_apply{rot}.png"
                (out / name).write_bytes(img_bytes)
                print(f"saved {name} ({len(img_bytes)} bytes)")


if __name__ == "__main__":
    main()

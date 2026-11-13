#!/usr/bin/env python3
"""
复现信息披露申请书 Paddle OCR-VL 解析结果

用法:
  poetry run python scripts/reproduce_paddle_parse.py "C:/path/to/file.pdf"

输出目录: logs/paddle_reproduce/<时间戳>/
  - ocr_vl_response.json  Paddle OCR-VL API 原始 JSON（长 base64 已截断）
  - md_content.txt        Paddle OCR-VL 原始 Markdown
  - anchor_markdown.txt   加锚点后的 Markdown（与 LLM 提取输入一致）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FILE_TYPE = "evaluation_filing"


def _truncate_large_strings(obj: Any, max_len: int = 200000) -> Any:
    """递归截断 JSON 中的长字符串（如 base64 图像），便于保存与阅读"""
    if isinstance(obj, dict):
        return {k: _truncate_large_strings(v, max_len) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate_large_strings(v, max_len) for v in obj]
    if isinstance(obj, str) and len(obj) > max_len:
        return f"<truncated len={len(obj)}>"
    return obj


async def main() -> int:
    parser = argparse.ArgumentParser(description="复现信息披露申请书 Paddle OCR-VL 解析")
    parser.add_argument("pdf_path", help="本地 PDF 路径")
    parser.add_argument("--env", default=None, help="dev / prod，默认读环境配置")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.is_file():
        print(f"文件不存在: {pdf_path}", file=sys.stderr)
        return 1

    out_dir = ROOT / "logs" / "paddle_reproduce" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    from src.services.paddle.client import PaddleClient, PaddleError
    from src.utils.anchor_markdown_converter import AnchorMarkdownConverter
    from src.utils.pdf_text_layer_supplement import (
        apply_supplement_to_parse_results,
        serialize_supplement_segments,
    )

    client = PaddleClient(env=args.env) if args.env else PaddleClient()
    print(f"Paddle OCR-VL: {client.ocr_vl_config['base_url']}{client.ocr_vl_config['endpoint']}")
    print(f"解析文件: {pdf_path.name}")
    print(f"输出目录: {out_dir}")
    print("正在调用 Paddle API，请稍候…")

    try:
        parse_result = await client.parse_file_with_strategy(
            file_path=str(pdf_path),
            file_name=pdf_path.name,
            business_file_type=FILE_TYPE,
        )
    except PaddleError as e:
        print(f"Paddle 解析失败: {e}", file=sys.stderr)
        return 2
    finally:
        await client.client.aclose()

    if not parse_result or not parse_result.success:
        err = getattr(parse_result, "error_message", "unknown") if parse_result else "no result"
        print(f"解析返回失败: {err}", file=sys.stderr)
        return 3

    raw_json = client._last_ocr_vl_raw_json
    if raw_json:
        (out_dir / "ocr_vl_response.json").write_text(
            json.dumps(_truncate_large_strings(raw_json), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    raw_md = parse_result.md_content or ""
    (out_dir / "md_content.txt").write_text(raw_md, encoding="utf-8")

    pdf_bytes = pdf_path.read_bytes()
    page_supplements, supplement_segments, page_paddle_bboxes = (
        apply_supplement_to_parse_results([parse_result], pdf_bytes)
    )

    file_data = {
        "file_type": FILE_TYPE,
        "file_names": [pdf_path.name],
        "md_content": parse_result.md_content or raw_md,
        "parse_results": [parse_result],
        "text_layer_page_supplements": page_supplements,
        "text_layer_supplement_segments": serialize_supplement_segments(supplement_segments)
        if supplement_segments
        else {},
        "text_layer_page_paddle_bboxes": page_paddle_bboxes,
    }
    anchor_md, segment_map = AnchorMarkdownConverter.convert(file_data)
    (out_dir / "anchor_markdown.txt").write_text(anchor_md or raw_md, encoding="utf-8")

    print(f"API JSON 已保存: {'是' if raw_json else '否'}")
    print(f"原始 Markdown 长度: {len(raw_md)} | 页数: {parse_result.total_pages}")
    print(f"锚点 Markdown 长度: {len(anchor_md or raw_md)} | 片段数: {len(segment_map)}")
    print(f"结果已写入: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

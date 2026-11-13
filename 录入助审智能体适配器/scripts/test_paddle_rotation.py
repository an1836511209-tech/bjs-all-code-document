#!/usr/bin/env python3
"""
用 Paddle 在线 API 检测 PDF 每页的旋转角度，
与 PyMuPDF 的 page.rotation 对比，验证是否存在双重旋转问题。

用法：
    python scripts/test_paddle_rotation.py
"""
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
import requests

# ========== 配置 ==========
API_URL = "https://99ad0cbcb59bc2kb.aistudio-app.com/layout-parsing"
TOKEN = "9783a2cb2c603ff1b7ea41f9eff49292716baee6"

PDF_PATH = r"C:\Users\an183\Desktop\文件资料\项目档案\大宗\央企实物3-2\央企三部-于浒-GR2022BJ1002368-2\2.pdf"

# PaddleOCR-VL 参数（与 paddle_config.py 一致）
PAYLOAD_OPTIONS = {
    "fileType": 0,  # PDF
    "useDocOrientationClassify": True,
    "useDocUnwarping": False,
    "useLayoutDetection": True,
    "useChartRecognition": True,
    "restructurePages": True,
    "layoutNms": True,
    "promptLabel": "ocr",
    "formatBlockContent": True,
    "repetitionPenalty": 1,
    "temperature": 0,
    "topP": 1,
    "minPixels": 147384,
    "maxPixels": 2822400,
}


def main():
    pdf_path = Path(PDF_PATH)
    if not pdf_path.exists():
        print(f"PDF 不存在: {pdf_path}")
        return

    # 1. 读取 PyMuPDF 的 page.rotation
    doc = fitz.open(str(pdf_path))
    print(f"PDF: {pdf_path.name} | 共 {doc.page_count} 页")
    print("=" * 60)

    pdf_rotations = {}
    for i in range(doc.page_count):
        p = doc[i]
        pdf_rotations[i] = p.rotation
        print(f"  page_idx={i:2d}  ui_page={i+1:2d}  "
              f"pdf_rotation={p.rotation:3d}°  "
              f"size={p.rect.width:.0f}x{p.rect.height:.0f}")
    doc.close()

    # 2. 调用 Paddle 在线 API
    print("\n正在调用 Paddle API ...")
    file_bytes = pdf_path.read_bytes()
    file_data = base64.b64encode(file_bytes).decode("ascii")

    headers = {
        "Authorization": f"token {TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "file": file_data,
        **PAYLOAD_OPTIONS,
    }

    # 绕过系统代理直连
    proxies = {"http": None, "https": None}
    response = requests.post(API_URL, json=payload, headers=headers, timeout=120, proxies=proxies)
    print(f"API 状态码: {response.status_code}")

    if response.status_code != 200:
        print(f"请求失败: {response.text[:500]}")
        return

    result = response.json().get("result", {})
    pages = result.get("layoutParsingResults", [])
    print(f"Paddle 返回 {len(pages)} 页结果")
    print("=" * 60)

    # 3. 对比分析
    print(f"\n{'page':>4s}  {'pdf_rotation':>13s}  {'paddle_angle':>13s}  {'actual_rotation':>16s}  {'状态':>6s}")
    print("-" * 60)

    issues = []
    for i, page in enumerate(pages):
        pr = page.get("prunedResult", {})
        dpr = pr.get("doc_preprocessor_res") or {}
        paddle_angle = int(dpr.get("angle", 0) or 0)
        pdf_rot = pdf_rotations.get(i, 0)

        # 修复后的实际旋转角
        actual = (paddle_angle - pdf_rot) % 360

        # 判断是否有问题
        # 修复前：直接用 paddle_angle 旋转 → 如果 pdf_rot!=0 且 paddle_angle!=0 可能双重旋转
        # 修复后：用 actual 旋转 → 应该正确
        if pdf_rot != 0 and paddle_angle != 0:
            status = "⚠️  需修复" if actual == 0 else "🔍 验证"
        elif pdf_rot != 0 and paddle_angle == 0:
            status = "✅ 正常"
        else:
            status = "✅ 正常"

        print(f"{i:4d}  {pdf_rot:13d}°  {paddle_angle:13d}°  {actual:16d}°  {status}")

        if pdf_rot != 0 and paddle_angle != 0:
            issues.append({
                "page": i,
                "pdf_rotation": pdf_rot,
                "paddle_angle": paddle_angle,
                "actual_rotation": actual,
            })

    # 4. 总结
    print("\n" + "=" * 60)
    if issues:
        print(f"发现 {len(issues)} 个双重旋转风险页面：")
        for iss in issues:
            print(f"  page {iss['page']}: pdf_rotation={iss['pdf_rotation']}° "
                  f"paddle_angle={iss['paddle_angle']}° "
                  f"→ 修复后 actual={iss['actual_rotation']}°")
        print("\n结论: 这些页面修复前会双重旋转（倒置），修复后 actual_rotation=0 不再旋转。")
    else:
        print("未发现双重旋转风险页面。")
        print("如果仍有页面倒置，请检查 PDF 原始内容方向。")

    # 5. 保存完整响应供分析
    output_dir = ROOT / "logs" / "paddle_rotation_test"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "ocr_response.json"
    json_path.write_text(json.dumps(response.json(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整响应已保存: {json_path}")


if __name__ == "__main__":
    main()

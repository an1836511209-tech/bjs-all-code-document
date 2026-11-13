# 材料解析与路由

先按文件签名识别格式，再使用扩展名辅助判断。所有解析结果保留文件名、页码/幻灯片/工作表和单元格范围。解析文本用于确认 MCP 查询输入，也在 MCP 返回 empty/failed 时作为材料 evidence 兜底写作的事实来源。

- DOCX/DOC：通过 Apache Tika 提取全文（含页眉页脚、批注），按空行拆分为段落 block，`recognition_method=tika`。
- PPT/PPTX：通过 Gotenberg（LibreOffice）转为 PDF，再走幻灯片多模态管线：渲染全部页为图片，逐页交给多模态模型识别，输出整页结构化文本，`recognition_method=multimodal`。
- PDF：按页面宽高比分类。横版页（width > height）占比 ≥50% 判为 `slide_scan`，走多模态逐页识别；否则判为 `document_scan`，整份 PDF 一次性调用 PaddleOCR layout-parsing，按返回的 `layoutParsingResults` 逐页组装 markdown block，`recognition_method=paddle_ocr`。中间页字符中位数仅作诊断告警，不改变路由。
- XLS/XLSX/CSV：读取工作表、已计算单元格值和表格范围，避免把公式字符串当作结果，`recognition_method=embedded_text`。

多模态模型只能查看工作区工具返回的页面图像，不允许访问宿主路径。OCR/视觉输出必须携带页码、方法和置信度。长材料按稳定页界或工作表边界分块，通过 `read_material_chunk` 按需读取，避免一次注入全部上下文。

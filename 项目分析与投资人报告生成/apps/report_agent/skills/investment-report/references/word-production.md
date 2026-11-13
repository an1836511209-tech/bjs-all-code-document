# Word 生产与交付

## Markdown 编辑模式

报告内容通过 Markdown 文件在工作区进行编辑和打磨，最后转换为 DOCX。

**工作流**：
1. 使用 `write_file` 在 `/workspace/report/report.md` 创建报告，编写 Markdown 内容。
2. 使用 `edit_file` 逐段追加和修改内容，反复打磨细节。每次只专注写一段（100-400字），写完检查够不够详细。
3. 使用 `read_file` 检查已写入的内容，确保数据准确和细节丰富，发现问题继续用 `edit_file` 修正。
4. 使用 `<!-- cite: evidence_xxx -->` 在段落或表格行后标注来源。
5. 编辑完成并自检无误后，调用 `create_word_from_md` 工具，将 Markdown 解析为 `ReportContent` 并生成 DOCX。此工具会自动校验 evidence_id 并生成 Word 文档。

**Markdown 格式规范**：
- `# 报告标题` (文档标题)
- `## 一、章节标题` (一级标题)
- `### （一）子节标题` (二级标题)
- 普通段落文本
- `| 列1 | 列2 |` (表格)
- `- 要点文本` (列表)
- `<!-- cite: evidence_xxx -->` (来源标注，放在段落或表格行后)

报告标题包含项目名称，标题 evidence 通过 `create_word_from_md` 的 `title_evidence_id` 参数传入。报告日期属于运行元数据，由调用方以 ISO 日期显式传入，不能由模型猜测；未传入时才使用运行环境日期。

## 批注

批注范围覆盖对应核心事实的完整文字或表格单元格文本，作者固定为"投资报告智能体"。批注面向业务用户，只展示自然语言出处说明、中文来源名称、网页 URL（如有）和 Evidence 中的原文或原始数据；工具名、`evidence_id`、`locator` 只保留在内部草稿和校验链路。创建 comments part、relationships、content type、comment range start/end 和 reference 后必须做结构校验，确保所有 id 成对且可解析。

## 验收顺序

1. 模型完成 Markdown 编辑并自检后，调用 `create_word_from_md` 生成 DOCX。
2. 调用 `add_report_comments` 添加来源批注。
3. 渲染全部页面，并对返回的每一个 PNG 调用 `inspect_report_page`，检查截断、重叠、孤行、表格跨页和空白页。
4. 校验章节、表格、批注作者、批注覆盖、关系文件和文件可打开性。
5. 通过后暂存不可变 artifact 并计算 SHA-256；失败文档修复后必须重新渲染和校验。

## MinIO 交付

只有服务侧 artifact service 可以读取凭据并上传。对象 key 使用不可猜测的 task/artifact 标识和安全文件名，上传时设置 DOCX content type、哈希和 Skill 版本元数据。返回有时限的预签名下载 URL，并同时返回 bucket/key、到期时间和 SHA-256。模型 Shell 不得直接连接 MinIO，也不得自动创建或修改 bucket。

---
name: word-document
description: 为 Report Agent 提供确定性的 DOCX 创建、编辑、真实批注、隐私清理和结构校验能力。主 Agent 不直接执行脚本；应用服务以 artifact_id 调用这些能力并创建新版本。
---

# Word 文档基础能力

## 边界

- 常规段落、样式、表格和页眉页脚使用 `python-docx`。
- 只有批注、修订和关系部件等能力不足时才修改 OOXML。
- 所有写操作产生新 DOCX，不覆盖已发布文件。
- 模型只传 `report_id`、`artifact_id` 和内容操作，不传文件系统路径。
- 来源批注由报告引用自动生成，不向读者展示内部 Evidence ID 或 JSON locator。

## 可复用脚本

- `docx_ooxml_patch.py`：底层 OOXML 补丁与批注关系维护。
- `comments_add.py`：按文本锚点追加真实 Word 批注。
- `comments_extract.py`：提取批注、作者、状态和锚定内容。
- `comments_apply_patch.py`：替换、追加和解决批注。
- `comments_strip.py`：同步删除批注锚点、部件、关系和 content type。
- `accept_tracked_changes.py`：接受或拒绝常见修订包装。
- `privacy_scrub.py`：清理作者、自定义属性和 rsid 元数据。
- `a11y_audit.py`：检查标题层级、图片替代文本和表头标记。
- `validate_docx.py`：调用项目 Word validator 做 ZIP、OOXML 与批注结构校验。

这些脚本是服务内部能力，不加入投资报告首次生成的模型工具清单。

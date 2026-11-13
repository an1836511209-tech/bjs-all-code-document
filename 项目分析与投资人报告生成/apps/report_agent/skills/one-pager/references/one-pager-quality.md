# 一页纸 BP 质量与 AI 痕迹审查口径

本 skill 复用现有 `check_report(md_path, checks=["quality","ai_tells"])`，与 `investment-report` 共用同一规则集。一页纸额外口径如下：

## 触发清单

| 来源 | 规则 |
|---|---|
| 正文明显溢出 | 介绍超过400 / 亮点超过220字 → preflight 拦截；225-250 / 170-185 仅作写作建议，不阻断渲染 |
| 缺章节 | 基本信息 / 项目介绍 / 项目亮点 / 投资人匹配 缺一 → quality.block |
| 占位符残留 | md 中残留 `{{*}}` 文本 → quality.block |
| 模板占位符漏替换 | 渲染后 `document.xml` 含 `{{`（在 service.render 自检） |
| 意识形态 | `review_ideological_text` 命中软档 R1–R45 → block |

## `check_report` 注入规则

调用时无需注入额外字段；`required_sections` 由 checker 默认值覆盖：

```
required_sections = ["## 基本信息", "## 项目介绍", "## 项目亮点", "## 投资人匹配"]
required_data_fields = ["项目名称", "公司全称", "所属区域", "所属行业",
                       "原始简介", "联系人名称"]
```

## 修策略（与 investment-report 一致）

| 触发 | 修法 |
|---|---|
| `template_transition` / `conclusion_cliche` | 删去"综上所述/由此可见"；用数据陈述替代 |
| `bureaucratic_phrase` | "具有重要意义" → "贡献 X 收入 Y%" |
| `ai_vocabulary` | "至关重要/显著提升" → 具体数字或"在 X 条件下提升 Y%" |
| `fake_specificity`（约 X%、约 X 人等） | 有当前材料依据则保留原值与“约”；无依据才删去或写“材料未披露”，不得改写成更精确的编造数字 |
| `list_overuse` | 拆为连贯短句 |
| 跨章重复 | 亮点段里改用"前述 / 上一段" |

## 阻断 vs 告警

- **block**：必须修，否则不进渲染
- **warn**：可保留并照常发布（如分号过多、空章节标题、引号风格）

## `PAGE_LIMIT_EXCEEDED` 不阻塞

渲染后 LibreOffice 生成的 PDF 页数 > 1 时，service 会 push 一个 warn 级的 `DocumentIssue`。agent **不应**因此阻断发布——agent 应记入 `missing_items` 草稿下一版收紧投资人行数。

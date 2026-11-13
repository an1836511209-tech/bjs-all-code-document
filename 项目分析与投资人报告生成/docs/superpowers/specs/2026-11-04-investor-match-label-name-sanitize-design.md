# Investor match `label_name` sanitize (strip per-tag quotes)

## Problem

DMP 请求体要求：

```json
{
  "label_type": "股权转让/增资",
  "label_name": "集成电路制造,高可靠功率半导体,宇航级元器件",
  "investor_type": "机构",
  "offset": 0,
  "limit": 30
}
```

`label_name` 是纯文本标签用**英文逗号**拼接，标签本身不加引号。

Agent / 上游偶发传入带引号的赛道标签（字符串或列表），经 `_join_label_names` / `",".join` 后变成：

```text
"住宿业","餐饮业","物业管理"
```

导致 DMP 匹配失败或结果偏差。投资报告 `match_investors` 与一页纸/工作台匹配表导出（`export_matched_institutions`）都会走到该出口。

## Goal

**自动清洗（不拒绝）**：在入参规范化阶段剥掉每个标签外层成对引号，再按既有分隔规则拆分；发出 DMP 的 `label_name` 始终是无引号的逗号串。

## Approach

统一在 `investor_match` 入参路径清洗，不改 DMP 契约字段名与固定值。

### Shared helper

新增 `apps/data_mcp/src/data_mcp/features/investor_match/tag_normalize.py`，导出 `strip_wrapping_quotes(tag: str) -> str`（避免 `service` ↔ `workbook` 互相 import）：

1. `strip()` 空白
2. 若首尾同为 `"` 或同为 `'`，去掉一层，再 `strip()`；可重复直到不成对
3. 返回清洗后的标签；空串丢弃由调用方处理

不做：删除标签内部的引号（只剥外层成对包裹）。

### Call sites

| 路径 | 改动 |
|---|---|
| `service._normalize_tags` | 拆分后（及 list 项）对每个 tag 调用 `strip_wrapping_quotes` |
| `workbook.normalize_track_tags` | NFKC/空白规范化后、非法字符校验前，先 `strip_wrapping_quotes` |
| `dmp_client._join_label_names` | 英文逗号 join 前对每项再 `strip_wrapping_quotes`（出口兜底） |
| `query_dmp_institutions_for_export` | join 前同样对每项 `strip_wrapping_quotes`，与报告路径出口一致 |

`label_type` 仍固定「股权转让/增资」；`investor_type` 仍由调用方传「机构」/「个人」。

### Separators (unchanged intent)

- 报告匹配 `_normalize_tags`：继续支持 `，` `,` `;` `；` `|`，以及 `[...]` 外壳剥离
- 导出 `normalize_track_tags`：继续 `_SEPARATORS`（含 `、` 与换行）
- 两处清洗规则对齐：拆完后都剥外层引号

### Examples

| 输入 | 规范化后标签列表 | DMP `label_name` |
|---|---|---|
| `"住宿业","餐饮业"` | `住宿业`, `餐饮业` | `住宿业,餐饮业` |
| `['"集成电路制造"', '"特种电子"']` | `集成电路制造`, `特种电子` | `集成电路制造,特种电子` |
| `集成电路制造,高可靠功率半导体` | 原样 | `集成电路制造,高可靠功率半导体` |

## Tests

- unit：`_normalize_tags` / `normalize_track_tags` 对脏引号与干净输入
- unit：`_join_label_names` 对已带引号的列表仍输出无引号逗号串（若做兜底）
- 不新增真实 DMP 集成测试

## Out of scope

- 改 DMP 网关 / 远程 API 契约
- 严格拒绝非法格式（用户已选自动清洗）
- listed_peer_match 的 `_normalize_tags`（非本匹配表路由；若后续发现同类问题可复用 helper）
- 前端展示文案 / skill 提示词大改（可选后续加一句说明，非本变更必须）

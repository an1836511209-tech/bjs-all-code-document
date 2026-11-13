# 投资匹配报告 — 长细则与边界情况

> SKILL.md 的伴侣文件。SKILL.md 只列骨架与硬约束；本文给出字段映射、参数模板、边界处理、常见坑。

---

## 1. read_evidence_pack 默认指针（详细版）

每个成功 MCP 后调一次 `read_evidence_pack(evidence_id)`（pointers 留空）。
需要更深路径时再 `read_evidence(eid, pointer)` 补读。

```json
// extract_project_profile 返回
{
  "evidence_id": "evidence_xxx",
  "data": {
    "profile": { ... },           // 11 字段画像
    "field_details": { ... },       // 各字段证据
    "conflicts": [ ... ]            // 字段冲突列表
  },
  "json_roots": ["/data"]
}
```
**默认 pack**：`/data/profile` + `/data/field_details`（字段 status=missing 时正文写「材料未披露」，不要补造）

```json
// query_track_labels 返回
{
  "evidence_id": "evidence_xxx",
  "data": {
    "tags": ["货币银行服务", "银行理财服务", "银行监管服务"],
    "sources": [ ... ]
  },
  "json_roots": ["/data"]
}
```
**必读路径**：`/data/tags`

```json
// match_listed_peers 返回
{
  "evidence_id": "evidence_xxx",
  "data": {
    "meta": { "corpus_size": 28, "matching_version": "retrieval_v2", ... },
    "peers": [
      {
        "证券代码": "000001.SZ",
        "证券名称": "平安银行",
        "PE": 5.13,
        "PB(LF)": 0.52,
        "PS(TTM)": 1.60,
        "track_tags": ["零售银行", "对公银行", ...],
        "industry": "银行业",
        "evidence": { "industry_chain_position": ..., "products_services": ... },
        "final_score": 0.83
      }
    ],
    "query": { ... }
  }
}
```
**默认 pack**：`/data/peers`（返回带 `row_srcs`，表中每一行用该行 src，不要整表共用一条）

```json
// query_comparable_valuation 返回
{
  "evidence_id": "evidence_xxx",
  "data": {
    "content": "在过去北交所项目中，未找到可比历史估值"
  }
}
```
**默认 pack**：`/data/content`

```json
// match_investors 返回
{
  "evidence_id": "evidence_xxx",
  "data": {
    "candidates": [
      {
        "name": "某产业资本",
        "investor_type": "机构",
        "source": "internal",
        "match_reason": "...",
        "citations": [
          {"source_type": "dmp", "source_name": "DMP 标签库", "source_url": "", "quote": "..."}
        ]
      }
    ],
    "counts": {
      "internal_institutions": 10,
      "internal_individuals_excluded": 88,
      "network_institutions": 3
    },
    "shareholder_filter_applied": true
  }
}
```
**默认 pack**：`/data/candidates` + `/data/counts`（candidates 带 `row_srcs`，名单每一行用该行 src）  
**注意**：`candidates` 只含机构；个人投资人**不进名单**，仅用 counts 计数。勿填写或臆测 `label_type`。

---

## 2. 步骤 2 — `parse_materials` 参数

```python
parse_materials(path="/workspace/input/<上传文件名>")
# 返回:
{
  "material_id": "material_xxx",      # 用于 read_material_chunk
  "evidence_id": "evidence_xxx",       # 用于 report title_citations
  "blocks": [...],
  "format": "docx"
}
```

**两个 ID 都要保留**：`material_id` 给后续 `read_material_chunk`，`evidence_id` 给 title 引用。

---

## 3. 步骤 3 — 先工商查询，再 5 个 MCP

材料读完后，第一件数据调用是 `query_company_registry(company_name=<材料正文中的企业名>)`。不要用上传文件名。

- 查到精确工商信息后，后面的 `company_name` 用 `/data/company` 里的登记全称。
- 查不到、名称不精确或接口失败时，使用工具返回的卡片。用户可填写精确名称后重试；仍然查不到就再次出现同一张卡片。
- 用户选择「跳过此步骤」后，按材料继续，登记项写「材料未披露」，不要再查企查查。

```python
# 0. query_company_registry（工商登记，先于下面五项）
query_company_registry(
  company_name="<材料正文中的企业名；用户补充后改用补充的登记全称>"
)

# 1. extract_project_profile（材料画像）
extract_project_profile(
  company_name="<3.0 的登记全称；跳过时用材料正文中的企业名>",
  material_url=None,
  file_info=<parse_materials 的 data.blocks 文本>,  # 二选一
  search_keywords=[...]
)

# 2. query_track_labels（赛道标签）
query_track_labels(
  company_name="平安银行股份有限公司",
  project_profile=<extract_project_profile 的 data.profile>
)

# 3. match_listed_peers（上市公司对标）
match_listed_peers(
  tags=["股份制商业银行", "零售银行"],
  summary="全国性股份制商业银行，零售业务为核心"
)

# 4. query_comparable_valuation（同类成交对标）
query_comparable_valuation(
  tags=["股份制商业银行"],
  summary="北交所过去 3 年银行类股权转让"
)

# 5. match_investors（潜在投资人）
# 内部首选 DMP（服务端固定 label_type=股权转让/增资，机构+个人各查一次）；
# DMP 不通才走内部库；网络侧仍走 HiAgent。agent 只需传业务三参。
match_investors(
  company_name="平安银行股份有限公司",
  track_tags=<query_track_labels 的 data.tags>,  # 多标签英文逗号或数组均可
  project_profile=<extract_project_profile 的 data.profile>
  # 不要传 label_type
)
```

**status 含义**：
- `success` → 可用
- `partial` → 有数据但降级，部分字段可能缺失
- `empty` → 本次没有合适数据，记 `missing_items`
- `failed` → 工具未形成业务结果，记 `missing_items`

---

## 4. 步骤 4 — 报告章节 cite 模式

每段正文末尾用 `<!-- cite: evidence_<eid> -->` 标注溯源：

```markdown
2024 年末本行资产总额 57,692.70 亿元，较上年末增长 3.3%。
<!-- cite: evidence_xxx -->
```

**多源合并**（同一段引多个 eid）：
```markdown
平安银行当前 PB 不足 0.5 倍，PE 约 5 倍。
<!-- cite: evidence_peers -->
<!-- cite: evidence_material -->
```

---

## 5. 步骤 4 — 引用 MCP 数据示例（peer 表）

```markdown
| 证券代码 | 证券名称 | PE | PB(LF) | PS(TTM) | 行业 |
|---|---|---|---|---|---|
| 000001.SZ | 平安银行 | 5.13 | 0.52 | 1.60 | 银行业 |
| 920008.BJ | 成电光信 | 78.78 | 7.57 | 9.87 | 计算机、通信和其他电子设备制造业 |
<!-- cite: evidence_match_listed_peers -->
```

注意：表格里所有 peer 数据点必须能在 `evidence_match_listed_peers` 的 `/data/peers` 数组里找到对应行。

---

## 6. 步骤 4 — 第六章空结构模板

即便 `match_investors` 返回 `empty`（无机构候选），**第六章必须写章节结构**。若 `counts.internal_individuals_excluded > 0`，可在分析章或明细章用一句话说明个人侧数量，仍不列表。

```markdown
## 六、匹配投资人明细

> **前置声明**：本清单基于公开信息整理的参考性名单，**不代表投资方形成投资意向**，最终投资决策以投资方独立判断为准。

### 编制原则

按优先级排序：原股东 > 同区域国资 > 直接产业链协同方 > 其他潜在投资人。理由须精准结合项目特点与投资人业务布局。本表仅列机构候选；个人投资人仅统计数量、不逐条列示。

### 投资人清单

| 投资人名称 | 投资人类型 | 受让理由分析 |
|---|---|---|
| _（本次未获得合适机构候选，待补）_ | | |
<!-- cite: evidence_match_investors -->
```

---

## 7. 步骤 5 — `create_word_from_md` filename 必带 `.docx`

```python
create_word_from_md(
  md_path="/workspace/report/report.md",
  report_id="investment_report_20260119",  # 任意合法 ID
  filename="平安银行投资人匹配报告.docx",  # ← 必带 .docx 后缀
  company_name="平安银行股份有限公司",
  title_evidence_id="evidence_xxx"  # parse_materials 返回的 eid
)
```

**错误示例（会被 word_reports 拒绝）**：
- `filename="平安银行投资人匹配报告"` ← 缺后缀
- `filename="/path/to/foo.docx"` ← 含路径

---

## 8. 步骤 5 — review_ideological_text 循环退出条件

```python
# 循环结构
while True:
  report_md = read_file("/workspace/report/report.md")
  result = review_ideological_text(text=report_md)
  matches = json.loads(result)["matches"]
  if len(matches) == 0:
    break  # matches=[] 退出
  # 否则逐条 edit_file 修正
  for m in matches:
    edit_file(path="/workspace/report/report.md", old_string=m["original"], new_string=m["suggestion"])
  # 自决不修的写到 decisions.ndjson
  # ...

# 退出条件：matches=[] 或每条自决处理写到 decisions.ndjson
```

**禁止**：单次 review_ideological_text 后就宣称"自检通过"。

---

## 9. 边界情况处理

| 情况 | 处理 |
|---|---|
| `parse_materials` failed | 报告数据缺口，写 `missing_items`，退出 |
| 5 个 MCP 全 failed | 章节写"暂无合适公开数据"+ `missing_items`，不要终止 |
| `match_listed_peers` empty | 第四章(一)写"暂无合适上市公司对标"+ `missing_items` |
| `match_investors` empty | 第六章写空结构（前置声明 + 编制原则 + 占位表）|
| `read_evidence_pack` 的 `missing` 非空 | 先 `list_evidence_pointers`，再对缺路径 `read_evidence` 补读 |
| 二次审查 | 用 `run_writing_review` 一次合并，不要连调三个 check_* |
| 工具返回 `status=partial` | 部分字段缺失，写报告时标注 "(部分数据缺失)" + `missing_items` |
| `review_ideological_text` 抛错 | 必须向用户说明"意识形态审查词表缺失，本报告未做意识形态自检" |

---

## 10. `missing_items` 数组的最终回复

最终回复末尾附：
```
## 缺失数据说明
1. extract_project_profile：failed（material_url 仅支持 http/https）
2. match_investors：empty（本次未获得合适潜在投资机构候选）
3. ...
```

**禁止**把缺失数据写成报告独立章节。

---
name: investment-report
description: 撰写并交付带真实 Word 来源批注的北交所投资人匹配报告——基于用户上传材料，用 Data MCP 五件套取数，输出 Markdown + DOCX + 真实来源 Word 批注。MUST-USE 当用户指定该skill或着提到：投资匹配报告、北交所、投资人匹配、IPO 投资人、PE/VC 匹配、行业研究 + 财务数据交叉。本 skill 始终输出"投资匹配报告 + 报告后审查"，交付物始终是投资匹配报告。
allowed-tools:
  - get_working_context
  - list_context_indexes
  - load_skill_reference
  - batch_edit
  - parse_materials
  - read_material_chunk
  - export_parsed_md
  - export_material_text
  - read_result_chunk
  - search_result
  - list_result_paths
  - read_evidence
  - read_evidence_pack
  - search_evidence
  - extract_project_profile
  - query_track_labels
  - match_listed_peers
  - query_comparable_valuation
  - match_investors
  # 主干 2026-10-26 新增的三个补充型工具
  - query_company_registry
  - search_company_web
  - query_cbex_listing_financials
  - export_investor_list
  - ask_user
  - review_ideological_text
  - run_writing_review
  - check_data_field
  - check_citation
  - check_ai_tells
  # 完成凭据要求 check_report(checks=["quality"]) = block_count 0；缺了它模型无法
  # 满足自己的验收条件，而 fabricated_number / state_claim_without_source 只在它里面。
  - check_report
  - create_word_from_md
  - edit_word_document
  - add_report_comments
  - manage_word_comments
  - validate_and_publish_word
---

# 投资匹配报告 — 5 步流程

## 思考强度写进执行计划

**在 `write_todos` 的每一步开头加一个方括号标签**，流程会按"当前进行中的那一步"自动决定思考强度：

```
write_todos([
  {"content": "[on] 步骤 2 解析材料 + 业务类型判定", "status": "in_progress"},
  {"content": "[on] 步骤 3 先工商查询，再五个 MCP 取数", "status": "pending"},
  {"content": "[deep] 步骤 4 投资人匹配（口径冲突要判断）", "status": "pending"},
  {"content": "[off] 步骤 5.2 把字段抄进正文", "status": "pending"},
  {"content": "[on] 步骤 5.3 写亮点（要有理由，不是搬运）", "status": "pending"},
  {"content": "[off] 步骤 6 渲染 docx + 发布", "status": "pending"}
])
```

| 标签 | 用在什么步骤 |
| --- | --- |
| `[off]` | 纯搬运：把字段抄进正文、改格式、修错别字、渲染发布 |
| `[on]` | 需要判断：选章节口径、把多处事实合并成结论、决定写不写某一节 |
| `[deep]` | 跨材料核对：数值对账、股权穿透、多来源口径冲突时取舍 |
| `[auto]` | 拿不准时用，交回默认 |

**`[deep]` 不是"想久一点"，是一个动作要求**：标了 `[deep]` 的那一步，动手前必须先在
思考里写出**至少两条互相冲突的候选或证据**，再写取舍理由。只标标签不列候选，等于
没标——实测两次，`[deep]` 的平均思考量反而低于 `[on]`。

**判定标准**：这一步如果做错了，是"抄错"还是"想错"？抄错用 `[off]`，想错用 `[on]`/`[deep]`。

> 这个标签同时是**给流程看的**和**给人看的**：计划列表里直接显示，评审时知道哪一步是机械步骤。
> 如果没有平台读取它，它就只是一段计划文字，规则依然成立。

## 什么时候必须先用 `deep` 再动手

- 同一指标在不同页出现两个值，要决定用哪个
- 要把「材料没写、但能推出」的结论写进正文（这时同时决定它该标 `reasoned` 还是 `unreasoned`）
- 投资人匹配为空或标签明显不匹配，要判断是数据问题还是真的没有

临时需要调整时再用 `set_thinking`（只影响下一次调用）。

## 工作前必做

**第一动作** `write_todos` 拆 5 步总任务：
- [ ] 步骤 1 初始化
- [ ] 步骤 2 解析 + 完整读材料
- [ ] 步骤 3 先工商查询，再 5 个 MCP + read_evidence_pack
- [ ] 步骤 4 按 outline 写投资人匹配报告 + 引用 MCP
- [ ] 步骤 5 二次审查 + 创建 docx + 加批注 + 发布

子任务清单在上面一次拆完。**后续只更新每一步的 `status`（pending → in_progress →
completed），不要重写整个计划**——计划内容变了才重写。每一步的标签（`[on]`/`[deep]`/`[off]`）
也要留着，它决定那一步的思考强度。**完成需可验证凭据**（文件存在 / 字段值 / 工具返回 status）。

> **批量修改优先**：一个文件要改多处时，用 `batch_edit` 一次改完，比一段一次
> `edit_file` 更快、也不容易改乱上下文。只有当 `batch_edit` 报某条 `old_string`
> 找不到时，才把那一条单独用 `edit_file` 重试。

## 步骤 1：初始化

**目的**：确认 task 上下文建立。
- 子任务：`get_working_context` → `list_context_indexes`
- **完成凭据**：task_id / workspace_id 都拿到
- **禁止**：未拿到 task_id 就调后续工具

## 步骤 2：解析材料

**目的**：解析用户上传文件、**读完全部内容**。
- 子任务：`parse_materials` → `read_material_chunk` 逐段读
- 若某次返回内容被截断（工具会说明"还有剩余，从哪继续读"），**按它的指引继续读，直到读完**
- **完成凭据**：`/workspace/evidence/` 下有证据文件 + 材料的所有段落都读过
- **禁止**：材料没读完就调 `write_file`，或在工商查询完成前调用其他 Data MCP 工具

## 步骤 3：先工商查询，再 5 个 MCP + read_evidence_pack

**目的**：先确定登记主体，再拿 5 个数据源的实际数据。

### 3.0 工商登记（材料读完后的第一件数据调用）

材料全部读完后、调用任何其他 Data MCP 工具之前，单独调用：

```python
query_company_registry(company_name="<材料正文里写明的企业名称>")
read_evidence_pack(evidence_id)  # 默认读 /data/company
```

- 公司名称取材料正文。正文只有化名时也先用该化名查一次。不要把上传文件名当成企业全称。
- 用 pack 里 `/data/company` 的 value。查到精确匹配后，后面所有 `company_name` 都用返回的登记全称。
- 查不到、名称不精确或接口失败时，工具返回问题卡片并暂停本轮。问句是「当前公司名称无法获取企查查数据，请提供精确名称。」选项是「填写精确名称」和「跳过此步骤」。不要再调用 `ask_user` 重复提问。
- 用户填写名称后，只用这个名称再次调用 `query_company_registry`。仍然查不到时，同一张卡片会再出现，可以继续填写，也可以跳过。
- 用户选择跳过 → 不再查询企查查，按材料已有内容继续。登记项缺失写「材料未披露」，不得把这次查询当成报告失败。
- **完成凭据**：`registry_lookup` 为已查到，或用户已跳过。

### 3.1 材料交给画像工具的正确方式（工商查询完成或跳过后）

`extract_project_profile` 需要材料全文，二选一：

```python
# 首选：上传对象存储拿 URL（材料完整，不受入参长度限制）
export_parsed_md(material_id) → {"material_url": "http://...", "chars": 7718}
extract_project_profile(company_name="<3.0 确认的登记全称；跳过时用材料正文中的企业名>", material_url="<上一步的 URL>")

# 备选：对象存储不可用时，传完整文本（禁止概括）
export_material_text(material_id) → {"text": "<完整正文>", "chars": 7718}
extract_project_profile(company_name="<3.0 确认的登记全称；跳过时用材料正文中的企业名>", file_info="<上一步的 text 原样>")
```

**禁止**：
- 把本地路径（`/workspace/input/xx.pdf`）传给 `material_url` —— 它只接受 http/https
- 自己概括材料再传给 `file_info` —— 曾把 7718 字压成 637 字，导致画像为空
- 子任务 1：依次调 5 个 MCP 工具（任一返回 `failed` 不连锁放弃，记 `missing_items`）
- 子任务 2：**每个成功返回的 `evidence_id` 只调一次 `read_evidence_pack(eid)`**（pointers 留空用默认包）。不要每个字段再单独 `read_evidence`，除非 pack 的 `missing` 里缺了你要写的路径。

| MCP 工具 | 默认 pack | 实际字段 |
|---|---|---|
| `extract_project_profile` | **`/data/profile`** + **`/data/field_details`** | 画像字段及字段级状态；`missing` 的字段写「材料未披露」，不要补造 |
| `query_track_labels` | **`/data/tags`** | 字符串数组 |
| `match_listed_peers` | **`/data/peers`** | `证券代码` / `证券名称` / `公司中文名称` / `PE` / `PB(LF)` / `PS(TTM)` / `营业收入` / `净利润` / `industry` / `track_tags` / `citations` |
| `query_comparable_valuation` | **`/data/content`** | 文本描述 |
| `match_investors` | **`/data/candidates`** + **`/data/counts`** | candidates：机构候选；counts：个人只计数不进名单 |
| `query_company_registry` | **`/data/company`** | 工商登记字段；`company=null` 表示无结果 |
| `search_company_web` | **`/data/searches`** | 网页摘要列表 |
| `query_cbex_listing_financials` | **`/data/annual`** + **`/data/latest`** | 挂牌财务；缺的指针会进 `missing`，属正常 |

### 3.2 两个补充型工具（材料不足时才调）

用于**补足材料缺失的公开信息**。它们**不替代** `extract_project_profile`，也不替代 3.0 的工商查询：

```python
# 材料没写主营业务 / 上市状态 → 补公开网页线索
search_company_web(company_name="<3.0 确认的登记全称；跳过时用材料正文中的企业名>", search_keywords="<企业名> 主营业务")

# 项目是北交所挂牌的 → 查挂牌财务摘要
query_cbex_listing_financials(project_name="<项目名>")
```

**调用原则**：

- `search_company_web` 只在 `extract_project_profile` 的字段 `status=missing` 时才补，不要无脑全调
- `query_company_registry` 已在 3.0 完成。它返回的是工商**登记**信息（认缴/实缴、股东、人员），不代表投资意向
- `search_company_web` 的结果是网页摘要，写进报告时 `kind=web`，并在 `src` 的 note 里带 `source_url`
- `query_cbex_listing_financials` 对非北交所项目必然 `empty`，属正常，不要写进报告
- `match_investors` 只返回**机构**候选；个人侧规模看 `counts.internal_individuals_excluded`，**不要**把个人写进名单表

- 路径不确定 → 先 `list_evidence_pointers(eid, prefix="/data")` 再 `read_evidence` 补读
- **完成凭据**：`evidence/index.json` 有 5 个成功 MCP eid，且每个成功 eid 至少做过 1 次 `read_evidence_pack`（或等价的 `read_evidence`）
- **`peer.citations` / `candidate.citations` 已是结构化出处数组**——pack 会在 `row_srcs` 里按行给出 src。可比公司表、投资人表**每一行用该行的 `row_srcs.src`**，禁止整表共用父级 src（否则会把 A 家的分数贴到 B 家）
- **`match_investors` 调用要点**：必传 `company_name`（3.0 确认的登记全称；用户跳过时用材料正文中的企业名，不要用文件名）、`track_tags`（优先 `query_track_labels` 的 tags）、`project_profile`；**不要传 / 臆测 `label_type`**。名单只列机构；个人数量用 `counts.internal_individuals_excluded`
- **禁止**：
  - 把工具 summary（如"本次获得 10 个候选"）当数据用
  - `empty` / `failed` 的 eid 不进报告也不进 read
  - 每个字段连调多次 `read_evidence`（默认用 pack）

## 步骤 4：写报告（按 outline + 引用 MCP）

**目的**：写 `/workspace/report/report.md`，章节严格按 outline，引用 MCP 字段。
- 子任务 1：`load_skill_reference("report-outline")` 加载章节骨架
- 子任务 2：**两批写入**（一次写六章易截断；四批又浪费模型轮次）：
  - 第 1 次 `write_file`：标题 + `## 一、报告头部` + `## 二、项目分析` + `## 三、市场分析`
  - 第 2 次 `edit_file`（追加）：`## 四、对标与估值参考` + `## 五、投资匹配分析` + `## 六、匹配投资人明细`
  - 若第 1 批仍被截断，可把「三、市场分析」挪到第 2 批，但不要回到四批
  - **标题格式**：
  ```
  # <项目名>投资人匹配报告
  ```
- 子任务 3：章节结构（6 个一级）：
  - `## 一、报告头部`
  - `## 二、项目分析`（`###（一）项目概况` / `（二）核心资产与业务模式` / `（三）财务状况`）
  - `## 三、市场分析` — 引用 `data.tags` 逐个列
  - `## 四、对标与估值参考`：
    - `（一）上市公司对标` — 引用 `data.peers[].证券代码/证券名称/PE/PB(LF)`
    - `（二）同类成交项目对标` — 引用 `data.content`
  - `## 五、投资匹配分析` — 引用 `data.candidates`（机构）类型 + 理由；可附带 `counts.internal_individuals_excluded` 说明个人侧规模
    - **「权重分数」口径要写清**：DMP 按投资人对项目的行为（浏览、关注、收藏等）给投资人
      打上项目标签，再用配置表定权重、衰减表衰减，求和得到该候选的**权重分数**。
      **正文、表格、批注、Excel 表头统一都叫「权重分数」**，不要再出现「匹配分」「权重和」
      「权重分」等别的叫法——同一个数有多个名字，审阅时无法核对。
    - 投资人表加**一行脚注**说明这个算法，业务方才知道分数怎么来的。
    - **每一行的权重分数必须和该行批注里的数值一致**。批注写的是别的行的数字，
      等于把 A 家的分数贴到了 B 家的行上。
  - `## 六、匹配投资人明细` — 机构清单来自 `data.candidates`；**即便 empty 也写章节结构**（前置声明 + 编制原则 + 候选人表占位）；个人不逐条列表
- 子任务 4：**写作即标注来源**（正文与批注一次写入，不是写完再补）
  - `read_evidence_pack` / `read_evidence` 的返回里带 **`src`** 字段，形如：
    ```
    <!-- src: mcp match_listed_peers /data/peers/6 ; 证券代码688012.SH / PE 78.40 -->
    ```
  - **把 `src` 原样粘到句子末尾**。这条标记同时承载「引用」和「批注」：
    - `kind` 决定 Word 批注标签（material→【原材料】、mcp→【MCP数据】、reasoned→【有因推理】…）
    - `tool` + `pointer` 记录数据出自哪个工具的哪个字段
    - `;` 后面的 `note` 就是最终批注文本，**可以改写成更贴合语境的说明**
  - `cite` 字段（`<!-- cite: evidence_xxx -->`）仍然保留，用于证据校验；
    **`src` 才是生成批注的那条**。**默认只贴 `src`**——它已经同时承载了批注锚点和证据指针，
    再补 `cite` 是冗余标记，白白增加正文长度和后续改写次数；只有审查明确报
    `uncited_sensitive` 时才补 `cite`。
  - 必标清单：注册资本 / 股权结构 / 财务数据 / 市场规模 / 增长率 / 政策名称 / 投资人匹配结果
  - 找不到来源 → 写「材料未披露」，**不要编数字**
  - 示例：
    ```
    ✅ 公司注册资本 13,180.00 万元。<!-- src: material parse_materials /data/blocks/1/text ; 原文：惠然科技有限公司，注册资本13,180.00万元 -->
    ✅ 中微公司 PE 78.40。<!-- src: mcp match_listed_peers /data/peers/6 ; 证券代码688012.SH / PE 78.40 -->
    ✅ 北京大兴区可能有地方引导基金参与。<!-- src: reasoned parse_materials /data/blocks/1/text ; 依据：材料第2页显示北京大兴有研发场地，按行业常识推断 -->
    ✅ 该数据材料未披露。
    ❌ 公司注册资本约 1.3 亿元。        ← 无 src 且用了"约"
    ```
  - **src 与段落一一对应**：一条 src 只标一个段落，多条数据请分句写、分别贴。
  - **状态词必须有出处**（自检项）：正文出现「已完成 / 进行中 / 未开始 / 验证 / 量产 /
    批量供货 / 小批量 / 定点 / 导入 / 推进」这类状态词时，必须引用一条**明确写出该状态**的
    证据块；引用不到就把那句改写为「材料未披露该状态」，**不要推测**。
    - 材料常用**图元**表达状态（进度矩阵、里程碑流程图）。这类页面的状态在文字层取不到，
      `read_material_chunk` 返回的 block 会带 `chart_heavy: true`。
    - 引用 `chart_heavy` 页面的结论时，必须加限定语「（该状态取自图表，文字层未展开）」，
      或者写「材料未披露该状态」。**把「已完成」写成「验证中」是最典型的错误。**
    - `check_report(checks=["quality"])` 会报 `state_claim_without_source`。这一项**不阻塞发布**，
      但它指的每一处都要么补出处、要么改写——这是审阅者最容易当场质疑的地方。
- **完成凭据**：`/workspace/report/report.md` 存在 + 6 个一级章节标题
  + `create_word_from_md` 返回的 `comment_count` 达到步骤 5 完成条件里要求的条数
  （src 标记会自动转成批注）
- **报告头部必须用两列表格**（不要写成 `**标的项目**：xxx` 的段落）：
  ```markdown
  ## 一、报告头部

  | 项目 | 内容 |
  |------|------|
  | 标的项目 | <项目全称> |
  | 报告日期 | <YYYY年M月> |
  | 证券代码 | <若有> |
  | 证券简称 | <若有> |
  | 转让方 | <若有，含持股比例> |
  ```
  原因：段落形式的 `字段：值` 会被 Word 的 `Body Text`（两端对齐 + 首行缩进）
  拉伸成「标 的 项 目 ： 平 安 银 行」；表格不会有这个问题。
- **禁止**：
  - 章节名用 outline 之外（扫描概况 / 识别的错误清单 等）
  - 标题用文件名 / 任务主题词（"意识形态错误识别报告"等）
  - **报告头部用段落写字段**（必须用表格，见上）
  - `**xxx**:` 行内加粗当小标题 — 用 `###（一）xxx` 升 Heading 2
  - 整章省略（即使 empty 也保留结构）
  - 把 MCP 工具的 `status`、`warnings`、`sources`、工具名、API 配置状态、兜底/降级策略等任何内部系统信息写入报告正文——这些仅供 agent 内部理解，报告是给用户看的

## 步骤 5：二次审查（合并非阻塞检查，只有意识形态循环）

**固定顺序**：`run_writing_review` →（有问题则一次 `batch_edit`）→ `review_ideological_text` → `check_report(checks=["quality","ai_tells"])`

不要再分别连调 `check_data_field` / `check_citation` / `check_ai_tells`。

### 5.1 写作审查（决策数据，一次完成）
`run_writing_review(md_path)` → 合并返回章节完整性、引用问题、AI 用语
- 看 `issues[]` 的 `kind` / `excerpt` / `terms`；`by_step` 可对照来源
- 缺章节或关键点：材料有则补写，材料无则写「材料未披露」
- `orphaned_citation` / `citation_mismatch` / `uncited_sensitive`：按 excerpt 补 cite 或改写「材料未披露」
- AI 用语：按 excerpt 改写；判断为必要表达可保留
- **有可修项时用一次 `batch_edit` 清完**，不要一段一次 `edit_file`
- `blocking=false`，但强烈建议全部处理

### 5.2 意识形态（唯一硬约束）
`review_ideological_text(text=<完整 report.md>)`
- `blocking=true` 时必须修到 `matches=[]`
- 每轮修完**重新调用**，直到 `blocking=false`
- 最多 5 轮；返回 `forced=true` 时停止并标记「需人工复核」
- **阻塞发布**

### 5.3 完成凭据复检
`check_report(checks=["quality","ai_tells"])`
- `quality` 与 `ai_tells` 的 `block_count` 都必须为 0
- 意识形态修改后确认没有破坏章节、引用硬项和 AI 用语硬项
- 这一步不能省略，也不能只跑 quality

- **不调** 任何审查工具在写报告**之前**或**过程**——只能对写好的完整 report.md 全文
- 子任务 6：`create_word_from_md(md_path, report_id, filename, company_name, title_evidence_id)`
  - **`filename` 必须以 `.docx` 结尾**（否则 word_reports 拒绝）
- 子任务 7：`export_investor_list(evidence_id=<match_investors 的 eid>, project=<项目名>)` → 全量投资人 Excel
  - 报告正文的投资人表只放**前 30 家**（按权重分数降序、机构优先）
  - 全量（最多 500 家）写入 `/workspace/report/<项目名>-投资人清单.xlsx`，在最终回复里给出文件路径
- 子任务 8：`add_report_comments(artifact_id, comments)` — 必覆盖：注册资本/股权/车辆/桩/财务/赛道标签/投资人/转让方/政策依据/市场规模与数字
  - **每条批注必须带 `kind`**，审阅者据此判断可信度：
    - `material` 材料原句的连续复制 → 批注写「出处：材料第 N 页；原文：<逐字原句>」
    - `reasoned` **把材料里两处以上事实组合成一个结论** → 批注写「依据：材料第 N 页 [+ 第 M 页]；推理：<一句逻辑链>」
    - `unreasoned` **材料里完全找不到、靠行业常识或经验** → 批注写「无材料依据，属经验判断：<判断内容>」
    - `web` 网上来源 → 写「来源：<发布机构>｜<标题或公告号>｜<链接>｜检索日期：<YYYY-MM-DD>」
      **四要素缺一不可**，否则读者无法复核这条信息是否真实、是否过时。
      `read_evidence_pack` / `read_evidence` 返回的 `src.note` 已经带齐这四项，直接用它。
    - `web_reasoned` 基于网上来源的推理 → 同上四要素，再加「；推理：<逻辑>」
    - **`mcp` Data MCP 返回的结构化数据** → 写「来源：<工具名>；字段：<json_pointer>；值：…」
  - **怎么选 kind**（从上往下判，判到就停）：

    | 这句话长什么样 | kind |
    | --- | --- |
    | 从材料里**复制**一句连续的话 | `material` |
    | 把材料里**两处以上**事实组合成一个结论（如「团队来自 AMAT」+「平均 12 年」→「团队壁垒高」） | `reasoned` |
    | 材料里**完全找不到**，靠行业常识/经验（如「该赛道受国产替代驱动」） | `unreasoned` |
    | 网上来源的原句 / 由其推出结论 | `web` / `web_reasoned` |
    | 接口返回的结构化字段 | `mcp` |

  - **两条禁止**：
    - **数字/比例/金额不得标 `reasoned`** —— 必须原始引用。把推导值伪装成材料事实，
      等于把「68/320 算出的 21%」写成「材料披露研发占比 21%」。
    - **`reasoned` 不许只写「基于材料推理」** —— 必须点明是**哪几页的什么事实**推出了这句话；
      写不出页码，就说明它其实是 `unreasoned`。
  - 工具会拒收不合规批注：`reasoned` 缺「依据」或「推理」、`unreasoned` 缺「无材料依据」都会被打回重写。
      - **`mcp` 类批注禁止写「原文：…」** —— 接口返回的字段不是材料原文，
        写成「原文」会让读者以为这是材料里的话。工具会直接拒收这类批注。
      - 例：`{"kind":"mcp","match_text":"招商银行","comment_text":"来源：match_listed_peers；字段：/data/peers[0].PE；值：7.31"}`
      - 适用：`match_listed_peers` 的可比公司表、`match_investors` 的投资人名单、
        `query_track_labels` 的赛道标签、`extract_project_profile` 的画像字段、
        `query_comparable_valuation` 的成交估值
  - **批注必须讲它所锚定的那一段的实体**：批注里出现的公司名，必须在 `match_text`
    指向的段落里也出现。否则就是把 A 家的资料写到了 B 家的行上（工具会拒收）。
  - `check_report(checks=["quality"])` 会报 `web_source_incomplete`，
    按提示把四要素补全。
  - **凡出现政策名称、金额、比例、数量的段落必须有批注**；找不到来源的数字不要写进报告
  - **MCP 数据必须有 `mcp` 批注**：正文里每个 cite 指向 MCP evidence 的段落，
    至少有一条 `mcp` 批注。只写 cite 不写批注，审阅者看不到来源。
  - **自检**：加完批注后数一下——
    - 报告里 MCP 来源的段落数 = N
    - `mcp` 批注数应 ≥ N
    - 若 `mcp` 批注数为 0，说明漏了整个 MCP 数据来源，必须补
- 子任务 9：`validate_and_publish_word(artifact_id)` → 真实 PublishedArtifact
- **完成凭据**：
  - review_ideological_text matches=[]
  - check_report(checks=["quality"]) block_count=0
  - check_report(checks=["ai_tells"]) block_count=0
  - `/workspace/artifacts/index.json` 有 status=published 的 artifact + comment_count ≥ 15
- **禁止**：
  - 第一阶段（步骤 1-4）任何时候调 review_ideological_text 或 check_report
  - 借修 AI 痕迹删事实 / 编造内容
  - filename 不带 `.docx`
  - 最终回复出现"参考:无 PublishedArtifact"或空话

## 长细则参见

- `references/investment-report-flow.md` — json_pointer 字段映射表 / cite 语法 / 边界情况
- `references/report-outline.md` — 章节骨架
- `references/ideology-terms.md` — 意识形态软档（R1–R45）

## 通用规则

- 缺失章节 → 进 `missing_items`，**不省略章节结构**
- 写错引用 → `edit_file` 立即修
- LLM 调用失败 → 一次重试，仍失败记 `missing_items`

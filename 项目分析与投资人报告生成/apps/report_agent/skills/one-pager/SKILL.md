---
name: one-pager
description: 撰写并交付单页 Word 推介文档——基于用户上传材料，调用 Data MCP 完成画像→投资人匹配，用模板 + 投资人匹配清单输出 .docx。MUST-USE 当用户指定该 skill 或着提到：一页纸、推介文档、单页 BP、one-pager。本 skill 始终输出「一页纸 BP + 投资人匹配表」，交付物是一页纸 Word。
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
  - extract_project_profile
  - match_investors
  # 流程图里的补数工具：工商登记 / 公开网页 / 北交所挂牌财务
  - query_company_registry
  - search_company_web
  - query_cbex_listing_financials
  - query_track_labels
  # 向用户提问（补充公司名称 / 材料支撑度 / 是否挂牌）
  - ask_user
  - detect_one_pager_business_type
  - check_one_pager_outline
  - render_one_pager
  - validate_and_publish_one_pager
  - review_ideological_text
  - check_report
---

# 一页纸 BP — 6 步流程

## 工作前必做

**第一动作** `write_todos` 拆 6 步，**每步开头带一个思考强度标签**：

```
[on]   步骤 1 初始化
[on]   步骤 2 解析材料 + 业务类型判定
[deep] 步骤 3 补数（赛道标签不匹配时要判断是数据问题还是真没有）
[deep] 步骤 4 投资人匹配（判断空结果是不是标签传导导致的）
[on]   步骤 5 写 one-pager.md（标题要自拟，亮点要有理由）
[off]  步骤 6 渲染 docx + 发布（纯机械）
```

| 标签 | 用在什么步骤 |
| --- | --- |
| `[off]` | 纯搬运：渲染、发布、改格式、修错别字 |
| `[on]` | 需要判断：自拟标题、把多处事实合成一段、决定写不写某节 |
| `[deep]` | 数据对不上、标签明显不匹配、要判断"是数据问题还是真没有" |
| `[auto]` | 拿不准 |

流程会按"当前进行中的那一步"自动决定思考强度——**不需要另调 `set_thinking`**。
判据：这一步做错了是"抄错"还是"想错"？抄错用 `[off]`，想错用 `[on]`/`[deep]`。

子任务清单在上面一次拆完，**后续步骤直接推进，不要重复调用 `write_todos` 重写计划**。

> **批量修改优先**：一个文件要改多处时用 `batch_edit` 一次改完，比一段一次 `edit_file`
> 更快、也不容易改乱上下文；审查工具一次报回多条问题时同样批量修。
> 计划只在第一步拆一次；后续**只更新每一步的 `status`**，不要重写整个计划——每一步开头的
> 思考强度标签要留着。

字数以 `render_one_pager` 的统计为准，来源标记和空白不计入正文。
225-250 / 170-185 字是写作建议，不是验收门槛。不得为了相差几字反复改稿，
也不得为凑字数新增事实。工具只拦截空段、结构错误和明显溢出（介绍超过400 / 亮点超过220字）。
不需要为了数字数去跑 shell——`read_file` / `edit_file` / `render_one_pager` 足够完成
写作、审查和发布；如果某个环境不提供命令执行能力，跳过它继续做，不要重试。

## 步骤 1：初始化

- 子任务：`get_working_context` → `list_context_indexes`
- **完成凭据**：task_id + workspace_id 拿到

## 步骤 2：解析材料 + 意图识别 + 业务类型判定

- 子任务 1：`parse_materials` → `read_material_chunk` 逐段读；内容被截断时按工具指引继续，**读到读完为止**
- 子任务 2：**意图识别**（自己判断，不调工具）
  - 材料与「一页纸 BP / 投资人概览」相关 → 继续
  - 材料与 BP 完全无关（例如财务报表、合同、会议纪要）→ `ask_user`
    问：「这份材料看起来不像项目材料，要继续生成一页纸 BP 吗？」
    选项：`["继续，我就是要用这份材料", "我传错了，稍后重新上传"]`
    选「重新上传」→ 结束本轮，等用户传新文件
    **问的时候要说清后果**，让用户能真的做决定，而不是被逼着点继续：
    - 这份材料缺什么（缺融资需求？缺拟出让比例？缺业务描述？）
    - 继续下去会得到什么（会写成了什么样子）
    - 一句话结论：能凑出一页纸但要素不全，还是根本写不出来
    不要只说"要不要继续"，那等于没给信息。
  - 用户意图模糊（只说"帮我看看"）→ `ask_user` 问清要一页纸 BP 还是其他
- 子任务 3：**材料质量判定**（自己判断）
  - 含优质项目信息（公司主体、业务、融资需求至少两项）→ 继续
  - 不含 → 记 `weak_material=True`，步骤 3.4 会触发公开搜索补数
- 子任务 4：**`detect_one_pager_business_type(material_path, filename, user_hint="")`**
  - `material_path` 可传 `/workspace/input/...` 原文件、`material_id`，或 UTF-8 文本；PDF/DOCX 等会自动用 `parse_materials` 后的正文，无需再导出文本
  - 返回 `business_type ∈ {"产权", "增资"}` 或 `status="needs_user_input"`
  - 若 `needs_user_input`，工具直接返回固定 `question_request`；系统自动显示「股权转让（产权）/增资扩股」卡片并结束本轮执行，不再依赖 `ask_user`，不要重复提问或继续调用后续工具。
  - 用户选择持久化到当前任务。继续时重新调用 `detect_one_pager_business_type(...)` 即可读取已确认类型，不得自行猜测或修改用户选择。未确认的模型 `user_hint` 不作为用户选择。
  - 若 `confidence="filename"` 且冲突 → 用材料判定结果，但提示用户
- **完成凭据**：1+ 个 evidence 存在 + `business_type` 已确定

## 步骤 3：补数（按顺序，缺哪个补哪个）

**原则**：先用材料，材料没有才补外部数据；每补一项都记进 `evidence`，写正文时用 `src` 标记。

### 3.1 工商登记（`query_company_registry`）

- 材料里**缺注册资本 / 股东 / 成立时间 / 法定代表人**任何一项 → 调
  `query_company_registry(company_name=<企业全称>)`
- 读 `/data/company`，把 `registered_capital` / `paid_in_capital` /
  `established_on` / `shareholders` / `主要人员` 补进画像
- **工商查询是可选补数，不是任务失败条件**。查询名称未精确匹配、查不到数据、接口失败时，保留材料已有信息，不得误用模糊匹配企业的数据，也不得把报告标记失败。
- 工具返回 `question_request` 时，系统自动显示可跳过卡片并等待本次选择，不再调用 `ask_user` 重复提问。
  问：「当前公司名称无法获取企查查数据，请提供精确名称。」
  选项：「填写精确名称」「跳过此步骤」。用户补充名称后，在同一任务用该精确名称重试；仍查不到时保留跳过入口，不自动循环查询。
- 用户选择跳过 → 使用材料已提供信息，缺失项记入 `missing_items`，直接继续步骤 3.2。不得再次查企查查或追问名称，除非用户主动要求重查。
- **完成凭据**：获得精确匹配的工商数据，或用户选择跳过。缺少 `credit_code` 不能单独阻断流程。

### 3.2 项目画像（`extract_project_profile`）

- 子任务 1：先用 `export_parsed_md(material_id)` 导出材料全文，得到 `material_url` 后调 `extract_project_profile(company_name, material_url=...)`。导出失败则 `export_material_text(material_id)`，把完整 text 原样传入 `file_info`；禁止概括材料，不得用工商查询结果替代材料全文。
- 子任务 2：`read_evidence(eid, "/data/profile")` 拿字段
- **字段缺失**：记入 `missing_items`，步骤 3.3/3.4 补
- **完成凭据**：profile 字段全部命中或记入 missing

### 3.3 赛道标签（`query_track_labels`）

- `query_track_labels(company_name=<企业全称>, project_profile=<3.2 的 profile>)`
- 读 `/data/tags`，用于「项目亮点」写赛道定位
- **标签为空**属正常（API 平台内网不可达时 HiAgent 兜底，仍空则跳过），不要因此中断
- **完成凭据**：`/data/tags` 拿到，或明确记录为空

**标签复核（必做）**：`query_track_labels` 返回的标签是接口按名称/画像召回的，
**不保证贴合**。逐个对照材料原文判断：
- 材料里有对应业务/产品 → 保留
- 材料里完全没有 → 丢弃，不要写进报告
- 全部都不贴合 → 报告中写「材料未披露明确赛道」，不要硬套接口标签

报告里注明一句「赛道标签来自 DMP 检索，经材料复核保留 N 个」，让读者知道做过这道筛。

### 3.4 材料支撑度检查 → 公开搜索（`search_company_web`）

- 判定：`weak_material=True`，或画像缺「主营业务」，或赛道标签为空 → 视为**支撑度不足**
- 支撑度不足 → **`ask_user`**：
  问：「材料信息偏少，是否用公开网络搜索补充主营业务与上市线索？」
  选项：`[{"value":"search","label":"搜索补充"},{"value":"skip","label":"不用，按材料写"}]`
- 选「搜索」→ `search_company_web(company_name=<企业全称>, search_keywords="<企业名> 主营业务")`
  读 `/data/searches`，把网页摘要折进画像；写正文时 `kind=web`，`src` 的 note 带 `source_url`
- **完成凭据**：`/data/searches` 有结果，或用户选择跳过

### 3.5 披露状态判定 → 北交所财务（`query_cbex_listing_financials`）

- **必须问**（材料里没写就一定要问）**`ask_user`**：
  问：「本项目是否为北交互联正在披露的项目？」
  选项：
  ```json
  [
    {"value":"yes","label":"是，正在北交互联披露","description":"将拉取披露财务摘要"},
    {"value":"no","label":"不是，普通股权转让/增资","description":"跳过财务数据"},
    {"value":"unknown","label":"不确定","description":"按材料已有信息继续"}
  ]
  ```
- 选「是」时必须请用户在卡片右侧填写北交互联正在挂牌的项目全称；只使用用户输入的全称，不得用公司简称或材料名替代。
- 用户提交全称后 → `query_cbex_listing_financials(project_name=<用户输入的项目全称>)`。
- 返回多个候选时系统自动显示项目选择卡片并暂停，用户选定后，使用选定的 `project_name` 和 `detail_url` 再次调用同一工具，直接获取该详情页财务，不重新搜索、不自行挑选。
- 读 `/data/annual`、`/data/latest` 和 `/data/detail_url`，用于「经营分析」段；仅使用已返回期间和指标。未获得财务时记入缺失项，按已有材料继续，不得把“正在披露”等同于“有财务分析”。
- 选「不是」/「不确定」→ 跳过，**不要**调该工具
- **完成凭据**：用户已回答（`yes` 且拿到财务，或 `no`/`unknown` 跳过）

## 步骤 4：投资人匹配（`match_investors`）

- 子任务 1：`match_investors(company_name, track_tags=<3.3 的 tags>, project_profile=<3.2 的 profile>)`
- 子任务 2：`read_evidence(eid, "/data/candidates")` → 内部库前 20 行
- **若内部 < 5**：标记信息不足，跳过；记 `missing_items`
- **完成凭据**：≥ 1 个投资人

## 步骤 5：先定大纲，再分段写正文，最后审查

**不得一次性写出完整 md**。分 3 个子任务，每步 `write_todos` 拆开。

### 5.1 定大纲（1 次调用出全部 6 个标题）

- 子任务 1：`load_skill_reference("one-pager-fields")` 读硬约束
- 子任务 2：判定两个条件槽位（有/无 `财务数据分析`、有/无 `非优质项目信息`）
  - 识别到非优质项目信息时，`has_risk_facts=true`，在第三个介绍槽位的 `key_points` 列出事实摘要，`source_quote` 提供材料原文依据。
  - 首次调用 `check_one_pager_outline` 会返回固定的「展示 / 不展示」确认卡片并暂停任务。不要重复调用 `ask_user`，用户回答前不得写正文或渲染发布。
  - 用户选择「展示」→ 重新校验大纲，第三个介绍标题固定为「风险提示」。用户选择「不展示」→ 重新拟定第三段标题和内容，不得在其他段落变相写入被排除的风险事实。
  - 内部的事实识别 `has_risk_facts` 和用户的展示选择 `include_risk_facts` 分开保存；后者由后端按用户回答设置，不得自行覆盖选择或重复询问。补充说明继续作为写作要求。
- 子任务 3：`check_one_pager_outline(outline={...})`

**决策表（强制）**：

| 槽位 | 条件 | 标题 |
|---|---|---|
| 介绍第 1 个 | 恒定 | **核心产品** |
| 介绍第 2 个 | 有财务数据分析 = 是 | **经营分析** |
| 介绍第 2 个 | 有财务数据分析 = 否 | 禁止用「经营分析」，自拟 3-6 字 |
| 介绍第 3 个 | 恒定 | 自拟 3-6 字；**禁止用「风险提示」** |

> **风险/非优质信息不占正文槽位**：它们由渲染层放到**第二页末尾的小字**里，
> 页首写「风险提示」。所以你只要把风险事实填进 `risk_facts`，正文第三段照常写
> 项目内容即可。免责声明由渲染层单独成页，你也不需要写。

- **完成凭据**：`check_one_pager_outline` 返回 `status="ok"` 并带 `decision_table`

### 5.2 写项目介绍 3 段正文

> **动笔前先读 `one-pager-writing`**（`load_skill_reference("one-pager-writing")`）。
> 它来自北交汇投实际交付的优秀样本，讲的是**怎么写**：小标题 + 论据的结构、
> 每句必须有可查证的实体或数字、禁止用评价句填空。这部分不遵守，字数是够的，
> 读起来仍然是空话。

- 子任务 1：`write_file` 创建 `/workspace/report/one-pager.md`，**只写到 `## 项目介绍` 三个正文为止**（亮点/投资人表先留空）
- 子任务 2：除「经营分析」外，每段正文建议 **225-250 字**，以材料事实完整为准。信息少时可短于建议范围
  - 组织建议：**小标题（4-8 字判断）+ 2-3 句具体事实**，不是无标题的大段叙述
  - 不手工逐字计数，不为建议范围反复调用 `edit_file`；只有工具报告硬上限溢出时才压缩对应段
  - **「经营分析」只写纯文本，禁止表格和表格分隔行**。建议 2-3 句、120 字以内，选取最新一期可核实的 3-4 个核心指标，保留期间、单位及「快报数」等口径。有可比数据时补一句趋势。完整财务明细留在材料底稿，本段按摘要取舍。

### 5.3 写项目亮点 3 段正文 + 投资人表

- 子任务 1：把 **5.2 写完的介绍全文**放进上下文，再 `edit_file` 追加 `## 项目亮点`
- 子任务 2：每段正文建议 **170-185 字**，不以凑齐字数为目标
  - **170-185 字 ≈ 4-5 句话**：1 个结论 + 2 个支撑数据 + 1 句影响或地位，不展开论证
  - 保留已有事实；目标范围之外但未超硬上限时直接进入审查与渲染，不再改字数
  - 结构示例（仅示意组织方式，不作为字数模板）：
    ```
    扫描电镜被科技部列为第 35 项卡脖子工程。7nm 制程电子束设备使用量是 28nm 的 4 倍，
    先进制程中电子束设备占比达 45%，国产化率不足 5%。公司相关产品已进入头部晶圆厂验证，
    并完成多台整机交付，是国内少数具备检测、量产与售后一体化交付能力的厂商。
    ```
  - 反例（过短或过长）：只写一句口号，或把市场规模、产能规划、竞争对手一起塞进亮点
    —— 这些属于「项目介绍」或已用过的事实，亮点只留最强的数据点再补一句影响即可
- 子任务 3：`edit_file` 追加 `## 投资人匹配` 表

正文写作使用 `<!-- src: material parse_materials /data/blocks/0/text ; 原文依据 -->` 来源标记；
兼容已有 `<src .../>` 标记，渲染器会自动剥离，不要为了更换标记反复重写。
同一文件的修改按顺序完成，不把重叠替换放在同一批并行工具调用中。
`write_file` 仅用于首次创建；文件已存在时先读取当前内容，再执行精确替换。

### 写作硬约束（违反即 block）

| 约束 | 内容 |
|---|---|
| **分工边界** | 项目介绍只写「是什么」：定位、构成、业务范围、产品线。**不承担价值论证**。项目亮点只写「为什么值得投」：数据、资质、成果、团队、市场地位。同一事实只能出现在其中一处。 |
| **句子级证据** | 每句必须能指出文档的具体依据（原文/具体数据）。指不出来的删掉。 |
| **完整性** | 「经营分析」按摘要规则选取核心财务指标。其余内容用上材料和工具已提供的具体事实，包括客户/供应商名称、产品型号、订单或意向数量、金额、专利数、认证名称及参与机构名。避免用「国内主要厂商」「多家客户」「行业领先」等笼统说法代替具体事实。 |
| **不要用判断填空** | 材料没给的信息，写「材料未披露」，**不要**用「占据有利地位」「降低产业化风险」「构成技术壁垒」这类没有事实支撑的评价去凑段落。审阅者一眼能看出这是空话。 |
| **禁止归因** | 材料未说明因果关系时，禁止「源于/得益于/反映出/受益于/正是由于/归功于」。改为分别陈述事实与结果，或写「材料未说明原因」。 |
| **数字** | 直接引用材料原值；不精确推算；同一数据只在其归属板块出现一次。 |
| **粒度** | 不写商业配套品牌名、单项设施占地面积、信用代码这类与投资判断无关的登记字段。但**注册资本、成立时间、员工/研发人数属于团队与规模信息，该写就写**。 |
| **人称** | 统一第三人称「公司」，不用「我们」。 |

### 5.4 三道审查

- `review_ideological_text(text=完整 md)` → matches=[]
- `check_report(md_path=md, checks=["quality"])` → block=0
- `check_report(md_path=md, checks=["ai_tells"])` → block=0
- 只修改 block 项；warn 不阻塞，block=0 后立即进入渲染和发布，不再为字数或告警重写
- **重点关注 `section_restatement`**：它意味着介绍段与亮点段在复述同一件事，按分工边界重写
- **完成凭据**：3 个审查调用全部返回 status=ok 且 block=0

## 步骤 6：渲染 docx + 发布

- 子任务 1：`render_one_pager(md_path, business_type, report_id, filename)` → artifact
  - **`filename` 必须以 `.docx` 结尾**
  - 返回含 `pages`、`valid`、`issues`、`investor_rows`
  - 若 `valid=False` 或 `notes` 非空 → 决策修，还是直接发布（注：`PAGE_LIMIT_EXCEEDED` 是 warn，不阻塞）
- 子任务 2：`validate_and_publish_one_pager(artifact_id)` → `PublishedArtifact`
  - 返回含 `object_key`、`download_url`
- **完成凭据**：
  - artifact `valid=True`
  - `PublishedArtifact` 返回（status=published）
  - 文件名以 `.docx` 结尾
- **禁止**：
  - 步骤 1-4 中调 `review_ideological_text` / `check_report`
  - filename 不带 `.docx`
  - 借修 AI 痕迹删事实或编造数据
  - 最终回复把 MCP 工具的状态/告警/兜底策略写入正文

## 长细则参见

- `references/one-pager-flow.md` — 字段映射与检测规则详解
- `references/one-pager-fields.md` — 字数约束与字段来源
- `references/one-pager-quality.md` — `check_report` 触发条件

## 通用规则

- 字段缺失 → 填「面议」「待定」+ 记 `missing_items`，**不阻断**
- 投资人全空 → 表格保留一行「暂无可用匹配数据」
- 业务类型无法判定 → 返回 `needs_input`，**不静默默认**
- 模板文件缺失 → 启动期报错，不静默兜底

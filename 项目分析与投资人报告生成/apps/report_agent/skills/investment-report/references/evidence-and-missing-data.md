# 证据与缺失数据规则

## evidence_id 不等于内容已读取

`parse_materials` 返回 `evidence_id` 只代表文件已解析并保存为 evidence 记录，**不等于模型已读取并理解了内容**。在通过 `read_material_chunk`/`read_result_chunk`/`read_evidence` 亲眼看到具体文本之前，任何基于该 `evidence_id` 写入报告的内容都属于编造。模型必须能在工具返回的原文中指出每个数据的具体出处文本，否则不准写入报告。

## MCP 状态处理

- `success`：只使用 `data` 中且能定位到 `evidence` 的事实。
- `partial`：只使用已有证据支持的子集，并在任务审计信息中记录缺失，不扩写缺口。
- `empty`：对应章节、段落、表格行或字段不生成。
- `failed`：记录错误并停止依赖该结果的写作；若影响关键交付，向用户说明需要补充或重试。

HTTP 200 不等于业务成功，必须依据统一响应外壳的 `status` 判断。

## 报告正文洁净性（硬约束）

报告是面向最终用户的交付物，不是 agent 的调试日志。MCP 工具返回的以下内部信息**仅供 agent 理解数据质量和完整性，绝对不得出现在报告正文中**：

- `status` 值（`success` / `partial` / `empty` / `failed`）
- `warnings` 数组中的 `code`、`message`（如"LMS 赛道标签 API 未配置""跳过调用并直接兜底"等）
- `sources` 数组中的内部来源名和状态（如 `lms: unavailable`、`hiagent: used`、`db_fallback: used`）
- 工具名（`query_track_labels`、`match_investors` 等）
- 任何关于 API 配置、兜底策略、降级逻辑、内部系统状态的描述
- "系统返回""兜底生成""API 未配置""数据为部分结果"等表述

**正确做法**：如果 `status=partial` 或有 `warnings`，agent 在内部判断数据可信度后正常使用已有数据写作，仅在 `missing_items` 中记录缺口。报告正文只呈现用户可理解的事实和分析，不暴露任何系统内部细节。数据缺失说明由程序在 Word 末尾统一追加，模型不在报告正文里自行补充缺失说明。

## Claim 门禁

项目主体、交易条件、财务数值、市场数值、日期、政策、上市公司指标、成交案例、投资人业务与匹配理由均属于事实性 claim。每个 claim 至少包含非空 `text` 和一个或多个 `EvidenceCitation`（仅含 `evidence_id`）。

**写入前自检**：对于每个要写入报告的 claim，模型必须能回答"这个数据/名称/表述是从哪个工具的哪段返回文本中读到的？"。如果回答不出，不准写入。仅凭 `evidence_id` 存在就写 claim 并挂 citation，属于"假引用"编造，是严重违规。

`evidence_id` 是 traceability 链接，指向已保存的 evidence 记录。模型通过 `read_evidence(evidence_id, json_pointer)` 语义读取 evidence 内容——`json_pointer` 只用于读取，不存入 citation。优先调用 `list_evidence_pointers` 查看索引，再用 `read_evidence` 精确读取；仅在需要连续原文时使用 `read_evidence_chunk`。

材料 Evidence（`parse_materials` 返回的 `evidence_id`）的 `json_pointer` 以 `/data/blocks` 为根，每个 block 含 `block_id`、`kind`、`text`。先用 `read_material_chunk(material_id)` 看 block 序号，再用 `read_evidence(evidence_id, "/data/blocks/N/text")` 读取具体文本。材料 evidence 的 `evidence_id` 与 `material_id` 不同——citation 必须用前者，`read_material_chunk` 用后者。

单个 MCP 结果为 `empty` 或 `failed` 时，先检查用户上传材料里是否确有对应事实——若有，改用 `parse_materials` 返回的材料 `evidence_id` 兜底 citation 并正常写作；若材料里也没有，将缺口记入 `missing_items`，省略所有依赖该结果的 claim、表格或整章，然后继续处理其他有证据的章节。不得因为局部缺数中止整份报告，也不得把"未查到结果"推导成行业偏离、没有投资价值或不存在投资人。最终 Word 由程序统一追加简短的数据缺失说明，只展示 `description` 的自然语言，不展示 `code`、工具名或内部字段；描述应直接写"未获取到……"或"未提供……"。

**读取材料内容时的注意**：材料很长时，`read_material_chunk` 一次返回的内容可能被截断，你会拿到一段摘要和"从哪里继续读"的说明。**必须按说明继续读完整内容再写报告**，不得仅凭摘要写报告——摘要截断会导致数据遗漏或虚构。

标题、固定免责声明和纯结构性连接句可以没有 citation，但不得夹带事实。

## 缺失输入

如果公司名称、交易标的或 Data MCP 工具所需参数无法从材料中唯一确定，应向用户提出最少且具体的问题。不得选择看似最可能的公司、行业或地区。

## Word 批注

Word 批注通过 `add_report_comments(artifact_id, comments)` 在 Word 生成后添加，是后处理步骤。模型为核心事实性 claim 提供批注，非核心段落不添加。每条批注包含：

- `match_text`：报告正文中的子串，用于定位要加批注的段落。**必须是报告正文中完整、精确、连续的文本**——不得改写、缩写或拼接不连续的文本。如果不确定精确文本，先调 `read_file` 读取 `/workspace/report/report.md` 确认后再写 `match_text`。`match_text` 匹配失败会导致批注丢失。
- `comment_text`：模型语义生成的完整批注文本，包含"出处说明、来源文件名、原文引用、数据含义说明"。

模型通过 `read_evidence` 读 evidence 后语义理解，自行组织批注内容。批注中不得展示 `evidence_id`、工具名、locator、凭据或服务器路径。一个句子由多项证据共同支持时应在同一批注列全。

Data MCP 的 `extract_project_profile` 使用 `data.field_details[].evidence[]`；`match_listed_peers` 使用 `data.peers[].citations`；`match_investors` 使用 `data.candidates[].citations`。后两者每条 citation 含 `source_name`（来源文件名或可读来源名）、`source_url`（网页，可空）、`quote`（原文或原始数据）。材料 Evidence 使用 `data.source_name` 与 `data.blocks[].text`。

### 批注必覆盖清单

以下数据**必须**添加批注，不得遗漏：

1. **注册资本和实缴资本**——match_text用报告中的"注册资本XXX万元"
2. **股权结构**——match_text用报告中的股东名称或持股比例
3. **车辆运营数据**——match_text用报告中的"XXX台"或车辆相关表述
4. **充电基础设施数据**——match_text用报告中的"充电站"或充电桩相关表述
5. **财务表中的每行数据**——match_text用报告表格中该行的指标名称（如"营业收入"、"净利润"、"净亏损率"）
6. **每个投资人名称**——match_text用报告中的投资人名称
7. **转让方和转让比例**——match_text用报告中的转让方名称或"15%股权"
8. **市场关键数据**——match_text用报告中的具体数据（如充电桩总数、网约车辆数等）

每条批注的 `comment_text` 应包含：数据来自哪个文件、原文是什么、数据的含义。不得只写"数据来源于XX文件"而不引用原文。

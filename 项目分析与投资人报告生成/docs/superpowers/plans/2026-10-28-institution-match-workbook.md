# 投资机构匹配 Excel 独立模块实现计划

- 初稿日期：2026-10-28
- 修订日期：2026-10-29
- 状态：代码已实现，本地配置启用；验证与启动方式见 [实施记录](../../change-notes/2026-10-29-institution-workbook.md)。容器、UAT、生产默认未启用。

## 一、本次变更与目标

新增独立的“投资机构匹配表”模块：复用当前项目的标签与材料，必要时精选标签，单独查询 DMP 机构接口，从机构标签列表核验命中项，生成 Excel。模块有自己的执行状态、预算和附件登记流程；原报告的完成提交和交付不等待该模块，其失败不能改变原报告内容、状态或下载。

**保留已确认条件：DMP 支持一次请求 200 条。本期固定 offset=0、limit=200，不分页、不循环补齐，不再重复验证这一前提。** 结果称为“首批最多 200 家”，不称为全部匹配名单。

| 原计划 | 本次修订 |
| --- | --- |
| 复用全部既有标签，不新增模型调用 | 优先复用标签；标签较多或来源需复核时，基于原材料最多调用一次选择器 |
| 三列，第三列名称像标签文本但实际是数量 | 保留数量字段并更名，新增第四列存实际命中的标签名称 |
| 完全不读取 label_name_list | 仅导出分支读取、求交集后丢弃，不带回原报告链路 |
| 报告返回前最多等 60 秒 | 报告先完成并交付，Excel 由持久辅助任务异步生成 |
| 假设通用附件遍历即可展示 | 明确改造 XLSX 预览、下载、附件状态查询和完成后的增量展示 |
| 独立调用仅指直接 MCP 调用 | 同时提供当前任务中的导出动作；不新建聊天、不重启报告 Agent |

默认 Excel 列名与顺序如下：

| 列 | 表头 | 来源与含义 |
| --- | --- | --- |
| A | 投资机构名称 | investor_name，文本 |
| B | 权重分数 | match_label_weight_sum，有限数值 |
| C | 匹配标签数（接口） | match_label_num，接口统计值，非负整数或空 |
| D | 匹配到的标签 | 本次实际查询标签与该机构 label_name_list 的可核验交集，文本 |

原第三列“匹配到的标签”更名为“匹配标签数（接口）”，第四列承担标签名称的语义。数量和名称均保留，不能把 match_label_num 当成名称，也不能用本地交集数量静默覆盖接口值。

工作表名为“投资机构”。有效机构为零时生成四列表头的空表，模块状态为成功，结果类别为 empty；查询失败不能伪装成零匹配。

## 二、当前实现事实与接入边界

已核对当前代码，实施时必须尊重以下边界：

1. 原 query_dmp_investors 同时查询机构和个人统计；_map_institution_items 主动删除 label_name_list，最多向报告提供 30 家机构。独立导出不能调用这条已裁剪的路径再尝试恢复标签，也不能把它改成保留原始长列表。
2. 原 query_track_labels 的共享契约 data 只有 tags，没有每个标签的置信分数或材料引用。不能按不存在的 confidence 字段排序，也不能再次往严格 data 对象塞入自定义选择信息。
3. 当前 evidence/index.json 记录工具、状态、路径、摘要和哈希，但未完整记录材料版本、公司和请求参数关联。“最近一条非空标签”不等于“属于当前公司与当前材料的标签”。
4. 现有 RunRepository.finish() 会更新任务/运行状态并登记附件。异步 Excel 不能再次调用它，否则会重新处理原报告完成流程。
5. 当前运行级 SSE 在 run.completed 后结束，前端也会关闭连接；只发一个迟到的 artifact.created 不能保证 Excel 出现。
6. 当前 addLiveDoc() 将文件按 Word 展示，单一 state.doc 也可能被新文件覆盖。需显式支持多文件与 XLSX，不能把 Excel 标成 Word 或让下载按钮绑定错误任务。
7. 一页纸检查点只管理原 Agent 的恢复。本模块不能借回答卡片启动它，也不能复用其 thread_id、修改 one-pager-execution.json 或将原报告从 completed 改回 running。

继续遵守 [2026-10-22 DMP 修复约定](../../change-notes/2026-10-22-dmp-word.md)：原报告仍裁剪长标签报文，原机构/个人数量、内部库、企查查、网络和股东过滤逻辑均不变。

## 三、模块结构、入口与交付顺序

### 3.1 职责划分

- Report Agent 辅助模块：解析当前任务上下文引用、选择标签、维护辅助任务、校验并上传 XLSX、追加附件。
- Data MCP 独立工具 export_matched_institutions：接收已选标签，只调一次 DMP 机构接口，清洗数据、计算交集并生成 XLSX。
- 标签选择器：使用小而受约束的模型调用；不创建原报告的 Deep Agent，不获得任意 MCP/文件写入工具。
- 前端：展示独立模块状态、Excel 文件页签/预览和稳定下载入口。

选择器不处理 200 行机构数据；Data MCP 不负责运行报告 Agent 或进行材料语义判断。

### 3.2 两种入口

聊天框新增“附带投资机构匹配表”复选开关，默认关闭，作为独立请求参数传输，不写入模型提示词。当前对话的卡片回答继承此选项；未开启时不记录附件上下文、不创建附件任务、不调用精选模型或额外 DMP。开启时在报告完成后自动入队。

1. **自动附带**：开关开启、本次 DOCX 属于当前任务且原报告已完成提交后，为该产物创建辅助任务。支持投资报告和一页纸，分别可配置开启。
2. **手动导出**：当前任务页提供“导出投资机构匹配表”动作，复用任务材料与标签，也可明确提交候选集合中的标签。无需已生成 Word，不启动新聊天或原报告流程。

直接调用 export_matched_institutions(track_tags=...) 仍受支持，不依赖 Word；此时调用方负责提供已经选定的标签。本期不新增独立站点或“上传材料只做 Excel”的新页面。

如果原报告还在运行，自动任务不启动；手动请求可先排队并显示原因，默认等原任务让出资源后执行。不能通过按钮补充消息误触发主报告路由。

### 3.3 主链与辅助链

~~~text
主链：材料 → 原有数据工具 → 写作/校验 → 发布 Word → 持久化 completed → 交付 Word
                                                         │
                                      可选提交通知 / 辅助 worker 补漏发现
                                                         ↓
辅助链：建立任务及输入快照 → 复用候选标签 → 按需精选
      → 新 MCP 工具 → DMP 机构一次请求最多 200 条
      → 标签交集与四列 Excel → 校验/上传 → 原子追加附件
                                           ↓
                           右侧新增 Excel 文件项、预览和下载

辅助链失败：仅更新辅助任务状态；原 Word、主任务状态和完成事件保持有效。
~~~

原报告结果组装和 run.completed 不等待 Excel、标签选择模型、DMP 或上传。删除旧计划中“在 ConfiguredAgentExecutor 返回前 await 最多 60 秒”的接入方式。

## 四、上下文复用与标签精选

### 4.1 默认复用，不重新跑报告

复用对象是已落地的材料解析、标签证据、画像和明确的用户补充，不是重新调用整个报告 Agent 的聊天线程。

| 可用上下文 | 处理方式 |
| --- | --- |
| 同公司、同材料版本的有效标签，数量不超过选择上限 | 默认直接复用，0 次标签接口、0 次选择模型 |
| 有效标签超过选择上限 | 复用候选和原文，最多 1 次选择模型 |
| 来源是需复核的本地召回等低可信候选 | 即使数量少也做一次材料核验/选择 |
| 相同输入已有合法选择记录 | 直接复用选择，不再调用模型 |
| 标签缺失、过期或不能确认属于本项目 | 自动导出跳过并说明原因；不启动全报告补数 |
| 用户明确要求更新标签，且有有效当前画像 | 仅调用一次 query_track_labels，再进入相同选择流程 |
| 材料解析缺失，或公司/画像归属不明 | 模块提示缺少上下文；不暗中解析全部文件或重跑五工具 |

手动更新标签是模块自己的可选操作，默认不发生。它使用独立超时，将结果留在模块快照，不覆盖主报告的证据、阶段或既有机构名单。

### 4.2 建立可核验的输入快照

为辅助任务保存不可变的 context_snapshot：

- task_id、origin_run_id、source_docx_artifact_id（手动无 Word 时可空）；
- 当前公司主体标识/全称；
- material_id、源文件 SHA-256、解析结果引用；
- profile_evidence_id 及内容哈希；
- track_label_evidence_id、状态、标签内容哈希及来源；
- 当前适用的用户补充/确认记录引用；
- context_fingerprint、选择策略版本、创建时间。

标签候选必须通过索引和载荷双重状态检查、工具名检查及引用哈希检查。仅接受同主体、同材料/画像输入范围内的 success 或 partial 非空结果；partial 中的失效/待复核信息必须保留。

实施时增加**可选的旁路上下文记录器**：在标签结果落地时记录输入关联，报告提交时固定实际上下文引用。主链 observer 只向有界队列非阻塞投递少量引用；持久化、材料读取/哈希和筛选由模块处理，不能在主工具回调中 await 网络、模型、DMP 或长文件操作。材料哈希优先读取原解析记录，不在主链重读大文件。

记录器不改工具响应、不进入模型消息；队列满、通知丢失或持久化失败只让 Excel 缺少可信上下文，不能让原 MCP 调用失败。通过参数/observer 注入，缺省不启用；丢失关联且无法验证补齐时明确跳过，不为追求自动出表而猜测来源。

旧工作区没有来源关联时，只能用可验证的原调用记录和材料哈希补齐；不能证明归属则跳过或请用户手动选择。不得仅按 evidence 索引插入顺序复用，更不能全局查找另一任务最近的标签。

任务入队时固定快照。之后材料/公司变更不改变已排队任务的输入；预览标明其来源版本。用户基于新材料再导出时创建新输入版本，不能将旧结果冒充新结果。

### 4.3 精选策略与模型约束

建议初始 max_selected_tags=5，可配置为 1～10；这是本模块策略，不是已验证的 DMP 标签数限制。

- 标签规范化后不超过上限且来源可信：使用全部候选。
- 超过上限或来源需复核：根据公司主营业务、核心产品及材料中的明确事实选择 1～上限个标签。
- 优先项目主体的实际业务，避免把合作伙伴、股东、泛行业背景或融资用途当作主营。
- 输入包含候选标签及材料原文片段，保留 material_id/块/页定位；画像用于辅助理解，不能只用生成的摘要替代原文。
- 长材料在本地按主营/产品等相关段落提取有来源的片段，设置输入上限，不让模型逐页调用工具。上下文不足时返回模块原因，不能只截材料开头便声称完成筛选。
- 输出必须是候选标签的子集，不允许创造、改名或扩大标签范围。可用候选 ID 输出，再由程序映射回原标签名称。
- 选择输出含理由和原文引用，逐项核对引用存在且属于当前材料；不把整段报告或机构名单放入选择输入。
- 不使用“接口前五项”或主观词频排序冒充模型选择。首版候选超过 max_candidate_tags=100 时明确提示人工缩小范围，不静默截断。
- 模型请求尝试最多 1 次，自动重试为 0；结构校验失败、无依据或不确定时辅助任务失败/跳过，可由用户手动选标签后重试，原报告不进入 needs_input。

选择结果持久化到模块自己的 selection.json，包含候选/选中标签、来源引用、理由、策略版本与指纹。原 query_track_labels 和 match_investors 的输入输出保持不变。

本模块按精选标签重新查询 DMP，原 Word 机构表还可能包含其他匹配来源或过滤规则，两者名单/排序不要求一致；预览说明本次查询标签及“首批最多 200 家”。

## 五、DMP 查询、命中标签与 Excel 规则

### 5.1 独立请求

复用现有环境配置、网关鉴权、签名和 _unwrap_payload 解包，新增独立请求函数。固定业务参数：

~~~json
{
  "label_type": "股权转让/增资",
  "label_name": "其他食品制造,速冻食品制造",
  "investor_type": "机构",
  "offset": 0,
  "limit": 200
}
~~~

- 不调用 query_dmp_investors，不调用个人、内部库、企查查或网络补名单。
- 不修改原 institution_limit、individual_limit、超时、重试或 _map_institution_items。
- 保留配置中的 GET/POST：GET 使用同字段查询参数，POST 使用 JSON。
- 每次正常导出只发一次机构请求，零自动重试、不跟随重定向；忽略 hasMore，不循环补齐。
- 分块接收并限制实际响应体为 64 MiB，不能只信 Content-Length；在有限 I/O 超时下检查总截止时间，超限关闭响应。
- 可在上限内完整解码 JSON，但需测试 Python 对象峰值内存；导出并发单独限制，初始为 1。
- 原始响应和长 label_name_list 只在导出处理过程存在，求交集后丢弃；不写 raw、原报告证据、模型上下文或日志正文。

### 5.2 标签求交集

令 Q 为**实际发给本次 DMP 请求的标签**，L_i 为第 i 家机构的 label_name_list：

~~~text
matched_labels_i = [q for q in Q if normalize(q) in normalize_and_split(L_i)]
~~~

Q 按选择顺序去重，输出按 Q 的顺序排列。不能与筛选前全部候选求交集。

规范化与解析：

1. 对字符串做 Unicode NFKC、首尾空白清理、规范空白；拉丁字母可统一大小写作比较，展示仍使用 Q 的原标签名。
2. 支持中英文逗号、分号、竖线、换行及字符串数组；兼容明确的 JSON 数组字符串。不能把“、”等实际出现的列表分隔符漏掉，也不能按普通空格任意切标签。
3. 采用完整标签相等比较，不做子串、模糊相似或未经确认的上下级/同义词扩展。“食品制造”不能自动命中“其他食品制造”。
4. 单机构标签去重；空值、非字符串元素、重复分隔符安全处理。
5. 源字段缺失、类型异常或带省略截断时，记录“未完整核验”标记。可确认的交集仍可写入，无法确认的项不补造。
6. 原始完整列表解析后即丢弃，只保留至多本次查询标签数的 matched_labels。

示例：

| 实际查询 Q | 机构 label_name_list | 新列输出 |
| --- | --- | --- |
| 其他食品制造、速冻食品制造 | 速冻食品制造,互联网零售,其他食品制造,零售业 | 其他食品制造、速冻食品制造 |
| 其他食品制造、速冻食品制造 | 资本投资服务,其他食品制造 | 其他食品制造 |
| 其他食品制造 | 食品制造 | 空，不做子串命中 |

### 5.3 数量差异与脏数据

- items 非数组为格式错误；空数组为正常零结果。
- 跳过非对象行、机构名非字符串或空名。
- 分数接受数值和数值字符串；布尔值、缺失、解析错误、溢出、NaN/无穷统一为 0.0，经 isfinite 校验后排序。
- 接口标签数只接受可无损解析、0～2**31-1 的整数；用 Decimal 等方式避免舍入，小数、负数、布尔值、非有限/超大值留空。
- 接口数量与本地可核验交集可能采用不同口径。数量不一致时保留接口数量和实际标签，不通过模糊匹配凑数，不将局部问题当作整个查询失败。
- 无法核验的标签名称留空或保留已核验项，并添加单元格注释；汇总 unverified_row_count、count_mismatch_row_count。含此类问题时 MCP 可返回 partial。
- 单条脏数据不阻断其他行；按权重降序稳定排序，同分保留接口顺序，最终最多 200 行，不自行按名称合并机构。
- 精简行对象只保留 investor_name、match_label_weight_sum、match_label_num、matched_labels；备注放单独的有界诊断结构，不保留 label_name_list。

### 5.4 工作簿与验证

使用现有 openpyxl，生成四列表格。机构名和标签按文本写入，防止以等号等开头的外部文本被当作公式；分数和计数按数值写，缺失计数用真正空单元格。

设置首行冻结、筛选、合理列宽；D 列自动换行，分数显示为 0.##。表头注释解释接口数量与可核验标签的区别。

文件名固定“投资机构匹配.xlsx”，MIME 为 application/vnd.openxmlformats-officedocument.spreadsheetml.sheet，SHA-256 对文件字节计算。有效零结果保留四列表头。

Report Agent 先限制 Base64 长度再严格解码，文件上限 2 MiB；校验 SHA、文件名、真实 XLSX 结构、工作表与四列表头、行数及基本类型，不能只检查 ZIP 文件头。读取校验还需有解压体积/条目上限。

## 六、MCP 契约与接口

新增 export_matched_institutions(track_tags: list[str] | str)，输入只允许 track_tags。分隔字符串与数组统一规范化，拒绝空标签；契约硬上限为 10 个规范标签，报告侧默认精选最多 5 个。工具接收的是最终选择，不再次调用模型。

统一输出信封保留原四状态。data 示例：

~~~json
{
  "filename": "投资机构匹配.xlsx",
  "content_base64": "<真实 xlsx 的 Base64>",
  "row_count": 200,
  "sha256": "<文件字节 SHA-256>",
  "query_tags": ["其他食品制造", "速冻食品制造"],
  "unverified_row_count": 0,
  "count_mismatch_row_count": 0
}
~~~

- success/partial/empty 均包含有效文件与上述字段；failed 可 data={}。
- row_count、两类诊断计数限制为 0～200，诊断数不超过行数；query_tags 必须与本次实际请求一致。
- 不返回 items、raw、label_name_list 或完整行数据；Base64 不进入 Agent 消息、原证据库或工具 trace。
- Report Agent 单独创建只含新工具的契约注册表和 transport，不走会写原报告证据的 DataMcpGateway.call。
- 新工具不加入 STANDARD_DATA_MCP_TOOLS、原写作工具面、五工具 readiness 或报告 Skill；只由辅助模块直接调用。
- Excel 实现调用时导入。工具缺失、导出凭证缺失、契约缺失只使辅助任务失败，不成为主服务启动硬依赖。

新工具须在专用边界清洗契约/文件异常：只保留固定错误码、字段路径和异常类型，不将原 ValidationError、HTTP 正文或异常链原样交给通用日志。尤其要防止 JSON Schema 错误把包含 Base64 的 data 对象打印出来；不得对原始错误直接 str()/logger.exception 后再声称日志已脱敏。原有工具的错误处理行为不在本模块中重写。

建议新增/调整的接口：

~~~python
def normalize_track_tags(value: str | list[str]) -> list[str]: ...
def match_requested_labels(requested_tags: list[str], raw_labels: object) -> LabelMatch: ...
def slim_institution_rows(items: object, requested_tags: list[str], *, limit: int = 200) -> SlimResult: ...
def query_dmp_institutions_for_export(selected_tags: list[str], env: str | None = None) -> SlimResult: ...
def build_institution_workbook(result: SlimResult) -> bytes: ...
def export_institution_workbook(track_tags: str | list[str], env: str | None = None) -> dict: ...

async def resolve_export_context(task_id: str, origin_run_id: str | None) -> ExportContext: ...
async def select_export_tags(context: ExportContext, settings: SelectionSettings) -> TagSelection: ...
async def execute_institution_workbook_job(job_id: str) -> None: ...
~~~

## 七、持久辅助任务、隔离与超时

### 7.1 最小持久层与触发

新增 report_agent_auxiliary_jobs 表，记录：

- job_id、task_id、origin_run_id、source_docx_artifact_id、job_type；
- 不可变输入引用、context_fingerprint、selection_fingerprint、策略/导出版本；
- status、stage、错误码、计时、worker 领取标识；
- workbook_ref/SHA、预分配对象键、artifact_id、创建/更新时间。

状态独立为 queued/running/succeeded/failed/skipped/cancelled，零行用 result_kind=empty 表达；不修改原主任务状态枚举。

模块由单独辅助 worker 进程执行，默认并发 1，拥有独立生命周期、模型预算和 I/O 客户端。可复用公共持久化/原子写能力，但不借用原报告 Agent 执行器或一页纸执行标记。

自动创建任务以**辅助 worker 有界发现已提交 completed 的 DOCX**为可靠入口。主报告完成后的可选通知仅做非阻塞唤醒，不在原返回路径等待数据库入队或新 worker 初始化，也不延长原运行的 active 标记；通知丢失由 worker 扫描补漏。记录关联不完整的旧报告只能跳过或手动导出，不能承诺无上下文也能自动补发。表未迁移/worker 未启动时，原报告照常返回。

自动幂等键包含任务、来源 DOCX/运行、上下文指纹和导出版本；同一输入不能因刷新、重复完成通知或断点恢复重复创建任务。手动刷新明确建立新版本；失败重试有新尝试标识，不重新生成 Word。

### 7.2 分阶段恢复与发布

stage 至少覆盖 context_resolved、tags_selected、request_started、workbook_received、uploaded、registered。

- 选择成功后即保存，DMP 失败重试可以复用选择，不再调用模型。
- XLSX 收到并校验后保存到任务专属有界文件，再推进 stage；恢复时可以只补上传/登记。
- 外部请求开始后、结果未落盘即崩溃，不能保证远端没有执行。首版将该尝试标记 interrupted 原因，等待显式重试，不无界重放查询。
- 主任务已完成但 Excel 失败/超时，只记录辅助状态与可理解原因，不调用原 resume、ask_user、fail 或 finish。

上传使用独立 MinIO 客户端和有界线程/I/O 超时；原 publish 的 staged DOCX 约束及共享客户端配置不变。对象路径至少包含 task_id/job_id，提前持久化对象标识，跨任务不共用附件记录。

新增 repository.append_auxiliary_artifact(...)：在一个事务中校验任务归属和领取标识、幂等插入附件、标记 job succeeded。不能再调用 RunRepository.finish()，不能覆盖原 Word、trace、assistant_text、skill 或报告耗时。工作区附件索引是可修复投影，不与数据库各自维护两套最终状态。

上传成功但登记前崩溃，可按同一对象键和 SHA 对账后补登记。取消/超时后的迟到结果必须通过任务状态、deadline 和领取标识校验，不能再追加附件。

### 7.3 初始配置与资源预算

报告侧新增可选配置，旧配置缺块时默认关闭：

~~~yaml
institution_workbook:
  enabled: false
  auto_after_report: true
  allowed_skills: ["investment-report", "one-pager"]
  max_concurrent_jobs: 1
  total_timeout_seconds: 120
  tag_refresh_timeout_seconds: 35
  selection_timeout_seconds: 25
  mcp_timeout_seconds: 45
  upload_timeout_seconds: 10
  context_validation_budget_seconds: 5
  max_workbook_bytes: 2097152
  selection:
    max_selected_tags: 5
    max_candidate_tags: 100
    max_material_chars: 24000
    max_model_attempts: 1
~~~

Data MCP 的 investor_match 下新增独立配置：

~~~yaml
workbook_export:
  request_timeout_seconds: 30
  max_response_bytes: 67108864
  max_concurrent_exports: 1
~~~

使用总截止时间，各阶段取自身预算与剩余时间的较小值；MCP 建立/调用/退出、文件处理、上传均计入。排队与执行耗时分别显示。旧配置缺块默认关闭；新块自身的类型/范围错误仍按现有配置校验规则处理，不把非法 YAML 承诺为可正常运行。

选择模型、DMP 和上传均零自动重试，不改原全局参数。用户明确刷新的 query_track_labels 只调用一次，但该工具内部仍可能有既有重试/模型兜底；独立预算覆盖这段等待，观测时区分选择模型与 Data MCP 内部模型次数，不能把“最多一次选择”说成整个链路总共只调用一次模型。

同步工作不阻塞服务事件循环，实施时验证框架执行方式或显式移入有界工作线程/进程；线程取消不能强行终止 I/O，必须有底层超时、结果领取校验和进程资源约束。Data MCP 导出路径单独限流，繁忙直接让辅助任务得到可重试原因，不能占满原报告工具处理资源。

这里的隔离保证是原报告的内容、状态与交付不依赖 Excel。共享机器仍有资源开销，需对辅助进程、响应大小和并发设限并测试原接口响应，不用一个 try/except 宣称完全资源隔离。

## 八、前端预览、下载与查询

### 8.1 模块 API

- POST /api/tasks/{task_id}/institution-workbook：创建辅助任务，接收 client_request_id、可选 expected_context_fingerprint、selected_tags、refresh_tags；严格校验任务归属、候选集合和标签上限。
- GET /api/tasks/{task_id}/auxiliary-jobs：返回模块任务状态、来源版本、简短原因及已登记附件；可给出不透明的附件版本标识供前端对账。
- GET /api/artifacts/{artifact_id}/content：继续复用稳定下载入口，增加 XLSX MIME 和正确文件名。
- GET /api/artifacts/{artifact_id}/preview：返回当前附件的四列、前 20 行、总行数、所选标签及有界诊断摘要；不返回原始 DMP 标签列表。

手动任务返回 202 + job_id/task_id，不新建 report run 或 conversation。显式 refresh_tags 最多单独更新一次标签；无有效画像时返回模块缺上下文原因，不转入原报告路由。

### 8.2 完成后的增量展示

当前主运行 SSE 已结束，因此首版使用独立的辅助状态查询/有限轮询：

- queued/running 时按有界间隔查询辅助任务，即使主报告为 completed 也继续；页面隐藏/切换可暂停轮询，重开任务时从服务端快照恢复。
- succeeded 时只增量合并新 artifact_id，刷新文件列表和右侧文件页签，不重放报告、不清空计划、不把主状态改为 running。
- failed/skipped 时仅显示模块提示与重试入口；主报告保持“已完成”，Word 下载一直可用。
- 新表/辅助查询不可用时只降级模块区域，不使整个任务快照接口失败。
- 后续可增加 task 级持久附件事件，不能依赖向已关闭的 run SSE 发消息。

### 8.3 文件类型与预览选择

将 addLiveDoc 等路径适配为按附件类型处理，运行时维护 artifactsById 和 activeArtifactId。Excel 成功后在右侧预览新增文件项/页签，显示四列表格预览与下载按钮；已有 Word 预览保持选中，不因后台附件抢焦点。没有当前预览时可选中新文件。

显示所选标签、“首批最多 200 家”和来源报告/材料版本。第三列注释说明为接口数量，第四列为可核验名称；异常提示仅在本附件内显示。

preview 从已验证的 XLSX 生成有界 sidecar，页面做文本转义，不直接渲染机构返回的 HTML。总表仍通过下载获取。所有按钮按当前 task/artifact 归属解析，正文、文件列表和右侧统一使用稳定 content 下载入口，不能缓存跨任务签名 URL。

## 九、实施文件与顺序

| 位置 | 实施内容 |
| --- | --- |
| data_mcp/features/investor_match/dmp_client.py | 新增导出专用请求/解包调用，保留原路径 |
| data_mcp/features/investor_match/workbook.py（新增） | 标签解析、交集、四字段精简、xlsx 与有限诊断 |
| data_mcp/shared/settings.py、mcp/server.py、mcp/responses.py | 可选配置、新工具及适配，惰性加载，不加原 readiness |
| contracts/mcp/export_matched_institutions.json（新增） | 已选标签输入、文件与有界元数据输出 |
| report_agent/application/institution_workbook/（新增） | 上下文引用/旁路记录、选择器、任务协调、校验与预览 |
| report_agent/infrastructure/persistence/、migrations/（新增迁移） | 辅助任务表、幂等领取与附件追加事务 |
| report_agent/infrastructure/artifacts/minio.py | 独立 XLSX 字节发布与有界客户端，保留 Word 默认行为 |
| report_agent/entrypoints/institution_workbook_worker.py（新增） | 辅助进程、补漏发现、恢复与停止 |
| report_agent/application/runs.py、bootstrap.py | 完成后可选通知与上下文引用记录，主链不 await 导出 |
| report_agent/api/app.py、settings/models.py | 模块 API、预览/MIME、默认关闭的配置 |
| frontend/assets/console.js、相关样式 | 模块动作、状态查询、多文件预览和绑定正确的下载 |
| deploy/environments 与部署说明 | 独立迁移、worker、预算/资源上限；测试先开，UAT/生产关闭 |

表中应用路径均相对于 apps/{data_mcp,report_agent}/src/；迁移和入口按各应用现有目录组织。具体迁移编号实施时选择空闲编号，不覆盖已有迁移或环境手工改动。

实施顺序：

1. 先完成 Data MCP 独立四列导出与原 DMP 回归，不接主报告。
2. 实现上下文快照、条件选择和指纹缓存，证明复用路径不重复模型/标签调用。
3. 实现持久辅助任务、独立 worker、幂等上传与附件追加，验证故障不改主状态。
4. 接入完成通知和手动模块 API，再做前端完成后轮询、预览与下载。
5. 测试环境以真实 DMP/MinIO 联调后开启；关闭开关停止新建任务，不移除已生成附件和原报告下载。

## 十、验证清单

已勾选项由本地自动化测试覆盖；未勾选项保留为部署/外部服务验收，不代表已通过。具体命令与结果见实施记录。

### 10.1 标签、机构行与工作簿

- [x] 同项目既有标签可复用；不同公司/材料/画像、失败/空标签、旧索引顺序不能误用。
- [x] 标签不多时 0 次选择模型；超量/低可信只调用 1 次；重试相同输入复用选择。
- [x] 选择是候选子集，逐项有原文依据，禁止捏造、只取前五、只靠摘要或越过标签/上下文预算。
- [x] 不确定/超时/非法结构只影响辅助任务，不新增主报告提问卡或模型运行。
- [x] 本次精选标签求交集：一项、多项、零项；未选中的候选和机构其他标签不进入新列。
- [x] 覆盖中文/英文分隔符、数组/JSON、重复/空白、全角、拉丁大小写、相近名称不误命中。
- [x] label_name_list 缺失、类型错、很长、带省略截断均有可解释输出；数量不一致不补造名称。
- [x] 覆盖机构脏行、非法/非有限分数、标签计数小数/负数/溢出，稳定排序与 200 行截断分别测试。
- [x] 重开真实 XLSX 验证四列表头、类型、空单元格、排序、文本而非公式、换行、零结果和 SHA。
- [x] 大长标签不使精简行/预览/模型输入膨胀；只有本次匹配标签留在导出内容。
- [ ] 一次机构请求、固定参数、GET/POST、鉴权、解包、超时/非 JSON/HTTP 错误/响应上限均验证。
- [x] 原 DMP 30 条裁剪、个人统计及原 match_investors 测试不变；新导出不改旧响应。

### 10.2 隔离、恢复与界面

- [ ] 开关关闭、缺配置/工具/契约/迁移/worker 时原报告照常交付。
- [x] 注入标签选择、DMP、文件校验、MinIO、登记失败及超时，原任务仍 completed、Word 可下载。
- [x] Word 完成事件与首份下载不等待选择模型或 DMP；辅助进程异常不会触发主 fail/resume/finish。
- [ ] 无 Word 的手动导出在上下文充分时可运行；原报告运行时遵循资源优先级，不启动第二个报告 Agent。
- [x] 重复通知/双击/页面刷新/worker 重启不重复选择和登记；未知外部调用状态明确处理，不无界重试。
- [ ] 上传成功登记前崩溃可对账；取消/超时后的迟到结果不能改主任务或追加附件。（迟到结果保护已测试；上传阶段进程崩溃后的完整对账仍待故障演练。）
- [x] 相同文件字节的两个任务归属、对象键和按钮隔离；输入变更不会把旧附件标成新版本。
- [x] Word completed、原 SSE 已关闭后，Excel 仍通过模块查询出现；刷新/切换聊天能恢复。
- [x] 右侧新增 Excel 页签有四列预览及下载，保留当前 Word；后台任务不能覆盖另一聊天的预览。
- [x] Excel 下载 MIME/中文名/字节正确，Word 下载行为、计划和状态不变。
- [x] 原始 items、label_name_list 和 Base64 不进入模型、主证据库、日志正文或主 trace。
- [x] 对含大 Base64 的无效 MCP 输出注入契约错误，日志仍只有固定码/字段路径，不出现载荷或完整异常链。
- [ ] 并发/大报文压力下原 MCP 健康和报告接口可响应，导出超限只影响辅助任务。

新增测试覆盖 Data MCP workbook/契约、Report Agent 选择器/任务/上传、数据库追加事务、API 与无头浏览器。用可注入模型和客户端计数/故障，不调用真实外部服务的测试必须可独立运行。

真实联调额外记录响应字节、有效行数、每阶段耗时、内存峰值和文件大小，不记录原始报文。实施后运行原投资报告、一页纸检查点、下载和 MCP 相关回归，已知基线失败单独记录，不宣称全库通过。

## 十一、本次交付边界

新 MCP、数据库迁移、辅助 worker、上下文与选择器、Excel 校验发布、聊天开关与预览下载均已实现。本地测试配置启用能力，聊天开关默认关闭；测试环境已执行新增附件表迁移。原投资报告匹配规则保持原实现，容器、UAT 和生产未启用该模块。

默认值（精选 5 标签、候选 100、辅助预算 120 秒）是初始策略，不是外部接口限制或性能承诺。真实 DMP/MinIO 联调仍待明确授权；自动审批拒绝了读取真实机构数据并临时上传的测试，当前不能宣称外部全链路已验收。

本期仍不提供完整名单分页；DMP 列表省略、同义词/上下级口径或接口统计差异导致不可核验时，应保留事实与提示，不能保证从缺失文本还原所有命中标签。

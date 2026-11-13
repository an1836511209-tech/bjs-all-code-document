## 16 对外接口详细契约

### 16.1 原有接口与文档差异

| 能力 | 原生方法与路径 | 使用方式 |
| --- | --- | --- |
| 文件质量 | POST /api/v1/file/quality-check | 复用 |
| 文件分类 | POST /api/v1/file/classification | 扩展材料注册表 |
| 披露辅助录入 | POST /api/v1/extraction/sync | 复用并增加四种extraction_type |
| 原有规则审核 | POST /api/v1/audit/sync | 保留实物契约 |
| 任务状态及结果 | GET /api/v1/task/{task_id} | type必传 include_details控制结果 |
| 任务取消 | POST /api/v1/task/{task_id}/cancel | type区分任务族 |
| 既有预览 | GET /api/v1/preview/files/{file_path:path} | 新业务需补鉴权与私有缓存策略 |

API DOCX文件分类标记待更新，代码已有task_id、timeout默认300000ms、status与统计字段，且支持classification任务查询；文档列出的提取业务status含timeout，但当前模型只有success/partial/pending/failed，timeout属于任务生命周期。统一参数校验当前为HTTP400 VALIDATION_ERROR。修订接口文档时以这些差异为专项验收项。

原生成功外壳为数值code=200。平台提供方默认前缀/api/platform/v1，成功业务头x-gw-biz-code为PS-001，x-gw-biz-msg提供说明；平台任务路径为GET /task?task_id=...&type=...以及POST /task/cancel?task_id=...&type=...。提供方不能伪造由平台生成的返回头。新车辆API必须新增平台路由、白名单、类型/编码和错误映射，不能假定自动透传。

平台当前未压缩JSON大小阈值为10×1024×1024字节，最终口径由接口联调确认。结果采用分页与受控文件引用，不能靠截断JSON降低大小。业务审核不通过仍是合法结果，HTTP200与PS-001不代表审核passed。

### 16.2 披露辅助录入参数与交互

| 字段 | 类型 | 必填与语义 |
| --- | --- | --- |
| extraction_type | string | 必填 四个新完整业务值或原四类值 |
| files | array | 新四场景非空且含相应申请书 |
| files[].file_url | string | 必填 受控URL或兼容原文件引用 |
| files[].file_name | string | 必填 展示名和辅助线索 |
| files[].file_type | FileType | 必填 扩展四种申请书材料枚举 |
| files[].file_content_hash | string或null | 可选 兼容MD5 服务端核验 |
| files[].file_size | integer或null | 可选 字节 |
| rule_config_id | string或null | 可选 必须启用且匹配场景 |
| request_id task_id | string或null | 兼容可选 新调用应传request_id |
| timeout | integer | 默认1000 最小1000 单位毫秒 同步等待窗口 |

四种拟新增材料枚举为property_transfer_pre_application、property_transfer_formal_application、capital_increase_pre_application、capital_increase_formal_application。它们是系统内部编码建议，中台材料编码需另行注册；不复用房屋产权证property_certificate代表产权交易申请书。

```json
{
  "request_id": "pt-pre-entry-001",
  "extraction_type": "产权转让-预披露",
  "files": [{
    "file_url": "https://example.invalid/files/application.docx",
    "file_name": "产权转让信息预披露申请书.docx",
    "file_type": "property_transfer_pre_application"
  }],
  "timeout": 1000
}
```

同步等待内完成则保留现有ExtractionData，返回results、统计和来源；未完成则data.status=pending并返回task_id。后续GET /api/v1/task/{task_id}?type=extraction&include_details=false只读生命周期，include_details=true获得结果。生命周期completed后result.status可能仍为pending，表示所有字段待确认，不能继续等待其自行完成。错业务、错阶段或核心材料无法识别时按第10章返回错误，同步与查询保持相同error结构。

### 16.3 机动车接口表

| 编号 | 方法与路径 | 输入或视图 |
| --- | --- | --- |
| V01 | POST /api/v1/vehicle/extraction/tasks | 创建录入任务 |
| V02 | POST /api/v1/vehicle/audit/tasks | 创建或重新触发助审 |
| V03 | GET /api/v1/vehicle/tasks/{task_id} | 生命周期和进度 |
| V04 | GET /api/v1/vehicle/tasks/{task_id}/materials | 附件匹配及归并 |
| V05 | GET /api/v1/vehicle/tasks/{task_id}/result | 固定运行版本的分页结果 |
| V06 | POST /api/v1/vehicle/tasks/{task_id}/split | 用户触发拆页子任务 |
| V07 | POST /api/v1/task/{task_id}/cancel?type=... | 复用取消 新增三种TaskType |

新增TaskType为vehicle_extraction、vehicle_audit、vehicle_split。车辆查询路由是同一TaskRepository的视图，通用task接口也支持这些type。创建成功沿用HTTP200和code200，返回TaskAccepted；不引入与旧接口冲突的新外壳。

### 16.4 创建录入与助审

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| request_id | string | 新机动车任务必填 最大128字符 |
| project_id | string | 必填 并验证调用方权限 |
| business_type | string | 必填 固定机动车-有纸 |
| disposal_mode | enum | 必填 auction或dismantling |
| rule_config_id | string或null | 可选 不传选当前发布快照 |
| files | array<VehicleFileInput> | 必填 非空 覆盖本轮有效材料 |
| trigger_type | enum | 助审必填 node_1或node_2 |
| extraction_task_id | string或null | 助审可选 同项目同模式的录入任务 |
| previous_task_id | string或null | 重触发可选 链接上一轮审核 |
| common_confirmed_fields | array | 助审必填 可以为空数组 |
| vehicles | array | 助审必填 非空 每实体含entity_id和confirmed_fields |

VehicleFileInput包含file_id、file_url、file_name、file_type、uploader_role以及可选entity_refs、file_content_hash和file_size。file_id在项目材料版本中唯一，uploader_role取operator/agency；服务端通过可信业务元数据校验来源角色，不能仅凭任意声明获得高优先级。输入文件引用的类型、长度、总文件数与大小受发布的接口配置约束。

ConfirmedField沿用field_name、field_value、field_type；机动车新增稳定field_id以便对照规则，field_type兼容原模型。entity_id与录入结果一致；纯人工录入场景由业务系统分配项目内稳定实体ID并传完整车辆确认数据，不强制依赖历史智能录入任务。

```json
{
  "request_id": "vehicle-entry-001",
  "project_id": "project-example",
  "business_type": "机动车-有纸",
  "disposal_mode": "auction",
  "files": [
    {"file_id": "f01", "file_url": "https://example.invalid/files/list.pdf", "file_name": "车辆处置明细表.pdf", "file_type": "vehicle_disposal_list", "uploader_role": "operator"},
    {"file_id": "f02", "file_url": "https://example.invalid/files/license.pdf", "file_name": "行驶证合并.pdf", "file_type": "vehicle_driving_license", "uploader_role": "operator"}
  ]
}
```

示例只说明结构，正式执行仍按规则检查全量材料。VehicleFileInput采用拟新增的内部材料编码，vehicle_driving_license与vehicle_registration_certificate分别表示行驶证和登记证。旧vehicle_certificate需重新识别细类，不能等价为两类证件齐备。

```json
{
  "code": 200,
  "message": "success",
  "trace_id": "trace-example",
  "data": {
    "request_id": "vehicle-entry-001",
    "task_id": "task-entry-001",
    "task_type": "vehicle_extraction",
    "status": "pending",
    "run_id": "run-entry-001",
    "created_at": "2026-11-04T10:00:00+08:00",
    "status_url": "/api/v1/vehicle/tasks/task-entry-001",
    "result_url": "/api/v1/vehicle/tasks/task-entry-001/result"
  }
}
```

时间使用带时区ISO8601，可统一存UTC；示例按北京时间展示。助审在相同结构上增加trigger_type、common_confirmed_fields与vehicles；重新触发须使用新request_id，可带previous_task_id，不覆盖原结果。

### 16.5 状态 附件匹配与分页结果

V03返回task_id、task_type、run_id、status、stage、progress、status_message、total_count、completed_count、error_message、error及创建/更新时间。stage取第9章阶段值，并补auditing与splitting，所有接口使用同一注册表；progress表示处理进度，不代表通过比例。

V04返回ready、items、missing_materials、unexpected_materials、ambiguous_materials和merge_decisions。items含file_id、声明及识别类型、match_status、适用条件、识别依据和evidence_refs；match_status沿用matched/missing/unexpected/ambiguous，缺失材料放在missing_materials且无伪造file_id。ready=false只表示尚未完成匹配，ready=true表示匹配阶段完成，不等价于材料齐全。

V05参数为run_id、cursor、page_size。run_id首轮可不传，服务端固定返回的运行版本；后续必须与游标一致。page_size建议默认20、范围1至100，正式上限结合平台10M字节限制与压测发布。游标绑定task_id、run_id、过滤条件和实体顺序并签名，过期或版本不符返回409 STALE_TASK_VERSION。未知任务或跨项目不可见任务统一404 TASK_NOT_FOUND。

结果外壳data包含第3.3节结构并新增next_cursor和has_more，只切分vehicles数组；common_fields、全任务统计及汇总属于同一固定快照，不按当前页重新计算，前端不得将多页汇总相加。每页车辆字段sources引用文件预览，不返回图片Base64；大范围证据与明细可另读受控对象引用。

pending/processing读取结果返回409 RESULT_NOT_READY并包含status；failed/cancelled/timeout返回409 TASK_NOT_COMPLETED及原error。completed允许返回result_status=partial，以及审核failed/pending结论。结果对象发布后不可变，run_id兼作该运行结果版本。

### 16.6 拆页与取消

```json
{
  "request_id": "vehicle-split-001",
  "parent_run_id": "run-entry-001",
  "file_ids": ["f02"],
  "entity_ids": ["vehicle-001"]
}
```

V06只允许引用已完成的vehicle_extraction父任务，parent_run_id和file_ids必填，file_ids非空；entity_ids可选，仅包含父结果中的实体。缺省不表示立即自动拆页，只有显式调用V06才触发。返回TaskAccepted，其中task_type为vehicle_split，并带parent_task_id和parent_run_id。

子结果包括split_results、unresolved_pages与summary。每个split_results项包含artifact_id、entity_id、plate_number、original_file_id、original_pages、file_name、download_url和status；本期按页拆分，original_pages每项仅一个原页号。summary.total_requested_pages等于success_pages加unresolved_pages_count加failed_pages，不得遗漏输入页。选择实体范围外的页记录skipped_pages并从requested_pages扣除，所有源页仍有映射清单。

父任务结果保持不可变，前端按entity_id关联子任务拆分结果。第3.3节父结果中的split_results初始为空，不随子任务更新；重新录入后拆页须引用新父任务及run_id。取消子任务不取消父任务。

V07沿用通用取消外壳，type为对应新TaskType。待执行任务可立即取消；执行中任务先持久化取消请求并返回当前status和可选cancel_requested=true，Worker确认后查询得到cancelled。已完成任务返回409 TASK_ALREADY_TERMINAL，不重置结果；重发取消请求应幂等返回同一取消状态。

### 16.7 平台和前端联调清单

平台侧新增三个TaskType、车辆路由、材料编码、错误映射、响应大小监控及鉴权主体透传；规则/预览等未被当前平台路由覆盖的入口需独立权限配置。不得将x-gw-appid或x-gw-org直接当成用户授权凭证。

前端按公共信息与车辆列表展示录入建议，按来源优先级显示差异；所有未识别车辆与页保留人工确认入口。助审显示四态与缺失理由、规则依据及原页截图，区分节点和历史版本；拆页提供显式勾选动作并展示未归属页；确认字段改变后提示旧审核结果已过期，由业务系统触发新审核。

## 17 需求到设计和验收的追踪

| 需求标识及原章节 | 需求主题 | 详细设计 | 验证 |
| --- | --- | --- | --- |
| VE01 一.3.1.1.1 | 附件匹配 缺失 类型错误 | 5及7.1 16.5 | T06 T09 |
| VE02 一.3.1.2.1 | 原生PDF文本 表格 坐标 | 3.4 5.1 | T23 |
| VE03 一.3.1.2.2 | Word段落 表格及位置 | 3.4 6.2 | T23 |
| VE04 一.3.1.2.3 | 规则匹配 来源优先级及提示 | 4及7.3 | T06 T10 |
| VE05 一.3.1.2.4 | 语义提取 | 4.3 7.3 | T06 |
| VE06 一.3.1.2.5 | 车辆数量 号牌跨文件统计 | 7.2 | T07 T08 T09 |
| VE07 一.3.1.3.1 | 一份公共信息 多条车辆 | 3.3 7.3 | T06 |
| VE08 一.3.1.3.2 | 用户勾选 按页拆分并命名 | 7.4 16.6 | T11 T12 |
| VE09 一.3.1.4.1 | 多来源一致性 片段和截图 | 7.3 8.5 | T06 T23 |
| VE10 一.3.1.5 | 提示词分组 样例 约束与调优 | 4.3 13 | 标注样本回归 |
| VE11 一.3.1.6 | 创建 状态 匹配 结果接口 | 16.3至16.5 | T18 T19 |
| VA01 一.3.2.1.1 | 经办机构取并集 同类机构优先 | 8.1 | T10 |
| VA02 一.3.2.1.2 | 号牌全附件比对 | 7.2 8.3 | T07 T08 T09 |
| VA03 一.3.2.2.1 | 异名同义字段 语义比较 | 8.3 | 初登日期样本 |
| VA04 一.3.2.3.1至3.2 | 数据交叉 内容审核 AND/OR | 8.3 8.4 | T13 |
| VA05 一.4.3.4.3 | 图像资产类型与号牌 | 8.3 | T16 |
| VA06 一.4.3.4.4 | 关联字段数值约束 | 8.3 | T15 |
| VA07 一.4.3.4.5至4.6 | 四态 例外 说明 | 8.4 8.5 | T13 T14 |
| VA08 一.4.3.4.7 | 原文截图及规则溯源 | 3.4 8.5 | T23 |
| VA09 一.4.3.5至3.6 | 提示词 重触发 状态 结果 | 4.3 9 16 | T17 T18 T19 |
| PT01 一.4.4.1 | 产权预披露解析 校验 提取 | 5 6 16.2 | T01 T02 T03 |
| PT02 一.4.4.2 | 产权正式披露解析 校验 提取 | 5 6 16.2 | T01 T02 T03 |
| CI01 一.4.5.1 | 增资预披露解析 校验 提取 | 5 6 16.2 | T01 T02 T03 |
| CI02 一.4.5.2 | 增资正式披露解析 校验 提取 | 5 6 16.2 | T01 T02 T03 |
| PC01 一.4.4.1.4 | 四场景共用接口 标准值和来源 | 6.2 16.2 | T01 T19 |
| WF01 一.2.1至2.2 | 拍卖解体两助审节点 | 8.2 16.4 | T17 |
| WF02 一.2.3 | 披露辅助录入后人工审批 | 1及6 概要1.3 | 业务流程联调 |
| NF01 一.5.1至5.4 | 架构 可扩展 规范 易用 | 2 4.3 16.7 | 评审及兼容检查 |
| NF02 一.5.5至5.6 | 180天审计 监控告警 | 11.3 | 审计保留/权限检查 |
| NF03 一.6 | 30并发 3秒 资源 模型指标 | 11.1 | T25 |
| NF04 一.7至8 | 兼容性 99.99% 零单点 | 11.2 12 | T20 T24 T25 |
| NF05 一.9 | 身份 网络 数据 加密 审计 注入 | 11.3 11.4 | T22 安全测试与演练 |

完整字段与规则级用例应在正式字段表和审核要点发布后细化为“规则ID—样本ID—预期值—证据页”的验收数据，不以本表的功能级覆盖替代业务正确性验收。

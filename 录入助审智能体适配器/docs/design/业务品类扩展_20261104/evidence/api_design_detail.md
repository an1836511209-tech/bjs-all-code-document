# 扩展接口详细设计建议

本节为拟新增或拟调整的契约，实施前须更新OpenAPI并联调。原有路径和字段保持兼容；示例字段及错误码是工程设计建议，具体业务字段以正式字段字典为准。

## 一 产权转让与企业增资共用提取接口

沿用 `POST /api/v1/extraction/sync`。extraction_type新增四个完整值：产权转让-预披露、产权转让-正式披露、企业增资-预披露、企业增资-正式披露。四场景分别选择规则快照。业务与披露阶段内部可拆成维度，外部不增加必填参数。

| 入参 | 类型 | 必填及约束 |
| --- | --- | --- |
| extraction_type | string | 必填；四个新增完整值或原四个实物值 |
| files | array<ExtractionFileInput> | 新辅助录入场景至少包含对应申请书；基于正文确认类别与阶段 |
| files[].file_url | string | 必填；沿用现有URL输入方式 |
| files[].file_name | string | 必填；只作线索，不作为业务识别唯一依据 |
| files[].file_type | FileType | 必填；沿用枚举并扩展或增加材料subtype；不把房屋产权证property_certificate当作产权交易申请书 |
| files[].file_content_hash | string或null | 选填；现有MD5兼容，服务端核验实际内容后参与缓存 |
| files[].file_size | integer或null | 选填；单位字节 |
| rule_config_id | string或null | 选填；存在、启用且匹配完整业务类型；无值则选场景默认配置 |
| request_id | string或null | 兼容选填，新调用方应提供；同一幂等重试保持相同 |
| task_id | string或null | 兼容选填；关联未完成任务，不能用来切换业务或材料 |
| timeout | integer | 默认1000，最小1000；仅控制同步等待，不是后台任务执行截止时间 |

业务配置、材料识别或集合匹配失败时停止后续提取。同步等待内发生错误返回400及结构化error；已经返回pending后发生错误，`GET /api/v1/task/{id}?type=extraction`仍以HTTP200返回查询结果，但data.status=failed、data.error=同一结构化错误。

任务状态查询使用 `include_details=false`；完整结果获取使用 `include_details=true`。这是复用一个HTTP接口提供两类视图，满足四场景共用的逻辑能力。响应保留现有results[]及SourceInfo。建议增量增加可选business_validation、rule_fingerprint和规则版本，不强制旧客户端读取。

## 二 机动车新增异步接口族

机动车结果为一条任务公共信息与多条车辆信息，建议采用独立接口族。以下路径仅为本次建议，尚未在仓库实现：

| 接口 | 方法与路径 | 响应data |
| --- | --- | --- |
| 创建车辆智能录入任务 | POST /api/v1/vehicle/extraction/tasks | TaskAccepted |
| 创建或重新触发车辆助审 | POST /api/v1/vehicle/audit/tasks | TaskAccepted |
| 查询生命周期与进度 | GET /api/v1/vehicle/tasks/{task_id} | VehicleTaskStatus |
| 查询附件匹配结果 | GET /api/v1/vehicle/tasks/{task_id}/materials | MaterialMatchView |
| 获取任务结果 | GET /api/v1/vehicle/tasks/{task_id}/result?cursor=...&page_size=... | VehicleResultPage |
| 创建按页拆分子任务 | POST /api/v1/vehicle/tasks/{task_id}/split | TaskAccepted，task_type=vehicle_split |
| 取消车辆任务 | POST /api/v1/vehicle/tasks/{task_id}/cancel | TaskCancelData |

创建成功以HTTP200及既有统一code=200响应，data.status=pending，立即返回task_id；不把车类批量处理挂在HTTP同步连接中等待。底层扩展TaskType为vehicle_extraction/vehicle_audit/vehicle_split并复用TaskStore；通用GET /api/v1/task/{task_id}?type=vehicle_extraction等以及POST /api/v1/task/{task_id}/cancel?type=vehicle_split扩展为支持三类新任务，ID解析器同步维护内部前缀。车辆族查询路径只是视图，不另建一套任务状态。平台接入需另外注册相同业务的适配路由及纳入路径集合，不会自动因新增直接接口而生效。

### 创建任务输入

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| request_id | string | 新任务必填；同主体及操作下幂等 |
| business_type | string | 拟为有纸机动车场景，正式外部值待联调确认 |
| disposal_mode | enum | 解体/拍卖的稳定编码待确认；参与规则选择和请求指纹 |
| rule_config_id | string或null | 选填，校验启用、业务、处置模式；创建后锁定规则快照 |
| files | array<VehicleFileInput> | 必填且非空；声明类型不能代替正文匹配 |
| previous_task_id | string或null | 助审重触发可选；关联上一轮，始终创建新任务并保留旧结果 |
| extraction_task_id | string或null | 助审可选，关联录入快照；必须属于同授权项目和场景 |
| common_confirmed_fields | array<ConfirmedField> | 助审使用；公共字段按需规字段字典校验 |
| vehicles | array<VehicleConfirmedItem> | 助审使用；每项有vehicle_id、车牌候选值、confirmed_fields |

VehicleFileInput含file_id、file_url、file_name、file_type、upload_stage、file_content_hash、file_size。file_id是调用方或服务端分配的稳定附件标识，同名附件不能只靠名称关联；upload_stage区分业务经办录入材料与服务机构助审材料，枚举和值由接口发布时固定。服务端从可信调用主体确定权限，不能据任意upload_stage声明授予跨项目访问。

新增行驶证与机动车登记证细分类，保证两类分别检查。旧vehicle_certificate作为兼容父类需再识别subtype；“已上传一个vehicle_certificate”不能等同两种证件均齐备。车辆处置申请、明细表、批复、委托函和照片等需要建立完整材料字典与平台编码映射，不在文档中虚构中台编码。

### TaskAccepted与状态响应

TaskAccepted：task_id:string、task_type:enum、status:pending、request_id:string、created_at:ISO8601。建议附status_url、materials_url、result_url三个相对地址，客户端按API服务基址解析。

VehicleTaskStatus：task_id、task_type、status、stage、progress、status_message、total_count、completed_count、error_message、error、created_at、updated_at、completed_at。status沿用pending/processing/completed/failed/timeout/cancelled；stage为receiving/classifying/parsing/validating/extracting/splitting/auditing/rendering等机器可读阶段，不把阶段硬塞到生命周期枚举。progress在0到1间，按已完成工作量计算；完成数不等于提取成功数或审核通过数。排队信息置status_message；任务状态失败时error包含业务码、可重试性和文件证据。

### 附件匹配视图

MaterialMatchView：task_id、ready:boolean、items[]、missing_materials[]、unexpected_materials[]、unrecognized_files[]、merge_records[]。匹配阶段完成前ready=false，可返回已识别项；ready=true时固定匹配快照。

每个items项包含file_id、file_name、declared_file_type、detected_file_type、material_subtype、match_status、required_condition、reason、sources[]。match_status为matched/mismatch/unrecognized；缺失是材料级记录，不能生成伪file_id。merge_records给出保留文件ID、替代文件ID、归并依据和上传阶段。归并须保留原件与审计记录，服务机构优先仅在确认同名同类型/内容等价的同一材料组内生效。

### 结果分页

结果GET仅在completed后返回结果；处理中返回409 RESULT_NOT_READY并给出当前status，不暗示任务失败；failed/timeout/cancelled返回409 TASK_NOT_COMPLETED及任务error；不存在或无访问权限返回404。轮询应优先状态接口。游标只对固定的result_version有效，page_size默认值与上限作为部署参数发布；所有页共用rule_fingerprint/material_manifest_fingerprint，避免混合不同重跑版本。

VehicleResultPage建议包含：task_id、task_type、result_version、business_type、disposal_mode、rule_config_id、rule_fingerprint、common_fields[]、vehicles[]、vehicle_statistics、cross_file_checks[]、file_audits[]、summary、next_cursor、has_more。公共信息、汇总及跨文件结论属于整个任务，分页只切vehicles，不按每页重算汇总。

vehicles[]含vehicle_id、plate_number、plate_status、fields[]、audit_results[]、split_files[]。vehicle_id为稳定实体ID；plate_number可空，plate_status可为identified/missing/ambiguous，不以随机车牌或VIN替代业务要求的号牌唯一匹配。车牌冲突、缺失、多号牌页须显式待确认，不能静默分配车辆。

车辆字段复用FieldExtractionResult的values、field_status及sources，并新增selected_value、selected_source_file_id、selection_reason、priority_hint等可选输出，明确高优先级源的选择与多来源冲突。selected_value不覆盖所有候选值；字段无有效值用null及待确认，不填空字符串假成功。

车辆统计至少记录必传基准文件ID、原始记录数、成功提取数、去重号牌数、重复号牌、无号牌记录、其他文件逐文件数量、missing_plates、extra_plates、consistency_status。不能仅返回一个总数或用所有附件记录相加得到车辆数。

split_files[]含split_file_id、original_file_id、vehicle_id、plate_number、original_pages（1起）、download_url、split_status、reason。新PDF的页序与原件页序同时保留；不能把拆分后的第1页冒充原附件第1页。重复车牌文件名需防冲突，同时满足按号牌命名。来源图与PDF采用受控URL引用，不将Base64图片塞入大批量JSON。

## 三 审核四态及证据

机动车专用VehicleAuditResult取passed/failed/pending/not_applicable，对应通过/不通过/待确认/无需审核。manual_review属于现有人工审核类型或动作，不能映射为无需审核。每项另设audit_status=completed/failed，区分规则执行失败与业务不通过。

单条审核结果保留audit_rule_id、audit_rule_name、vehicle_id（公共规则可空）、related_fields、audit_points、audit_result、audit_explanation、sources[]。failed/pending必须有说明；passed/not_applicable按需规不要求说明，但可记录内部适用性依据供审计。依赖文件缺失、解析失败、低置信度、条件不足原则上pending；符合明确免审条件才not_applicable。AND/OR规则、图像机动车/非机动车识别、照片号牌比对的结论均需绑定实际证据，模型未能判断不能当通过。

新summary包含total、passed、failed、pending、not_applicable、execution_failed，定义总数为实际生成的原子审核项，不直接复用现有只统计部分字段审核的summary口径。任务completed意味着执行结束，summary.failed>0仍可completed。

SourceInfo复用现有文件名、来源字段、内容、page_number、coordinates、confidence、preview_image_url、regions等字段，增量增加source_file_id、vehicle_id、original_page_number、coordinate_space、page_width、page_height。page_number对外1起，regions.page_idx内部0起；坐标单位、基准页尺寸及是否旋转以元数据明确。Word转PDF后应返回渲染文件ID和渲染页码映射；无法获得真实坐标时trace_supported=false，不伪造零坐标有效截图。

## 四 错误结构与状态码

沿用顶层code/message/trace_id/timestamp与error.error_code/error_message/details，新增可选error.retryable。ErrorDetail增量加入file_id、file_name、vehicle_id、expected_business_type、detected_business_category、expected_disclosure_stage、detected_disclosure_stage、page_number、evidence。日志/界面仅返回排查所需片段，避免整份原文或密钥进入错误响应。

| HTTP | 拟新增业务码 | 触发与动作 |
| --- | --- | --- |
| 400 | BUSINESS_TYPE_MISMATCH | 申请书实际品类与请求不一致，停止提取 |
| 400 | DISCLOSURE_STAGE_MISMATCH | 明确阶段不兼容，停止提取 |
| 400 | MATERIAL_SET_CONFLICT | 多份核心材料互相冲突，列明冲突文件 |
| 400 | REQUIRED_MATERIAL_MISSING | 必需申请书/必传材料缺失，列明材料项与适用条件 |
| 400 | MATERIAL_BUSINESS_UNDETERMINED | 有核心材料但无法确定类型，提示换件或人工核对 |
| 400 | RULE_CONFIG_INVALID | 不存在、禁用或场景不匹配，禁止跨场景复用 |
| 409 | TASK_REQUEST_CONFLICT | 同幂等键不同请求指纹，创建新请求标识 |
| 409 | RESULT_NOT_READY | 结果尚未形成，仅继续轮询 |
| 409 | TASK_NOT_COMPLETED | 已失败/取消/执行超时，读取任务错误并按策略重触发 |
| 404 | TASK_NOT_FOUND | 任务不存在、类型不匹配或不可见 |
| 413 | PAYLOAD_TOO_LARGE | 响应超网关限制，改用分页与文件引用 |
| 429 | RATE_LIMITED | 接入或并发限制，按Retry-After退避 |
| 502/503 | PARSE_SERVICE_UNAVAILABLE等 | OCR/LLM/存储依赖异常，可重试与否由服务端分类 |

HTTP200的失败任务查询表示“查询成功”，data.error表达任务失败；平台响应头不可把任务处理失败误导为审核通过。成功取到包含failed业务审核项的completed任务是合法业务结果，不能返回服务器500。

## 五 幂等与可恢复性

幂等键由可信调用主体、操作类型和request_id组成，请求指纹包含业务及阶段/处置模式、规则指纹、服务端核验的附件清单、待审字段和归并策略。创建时用原子占位与比较避免两节点同时创建；同指纹返回同一任务及当前结果。更新材料或确认字段需新request_id和新任务快照；助审previous_task_id只作关联。完成结果不可就地覆盖。

实现区分两个指纹：创建幂等指纹基于规范化的原始请求（含明确规则ID或默认配置选择意图、附件引用、待审值），在下载前即可原子占位，第一次创建同时锁定实际默认规则快照；有效处理指纹在下载后用服务端计算的内容SHA-256、实际规则/提示词/归并与拆页策略指纹生成，用于业务结果缓存。已有file_content_hash继续按兼容MD5解释，不能把调用方MD5直接当成可信SHA-256。短期签名URL变化的幂等重试宜使用稳定file_id；未引入稳定附件ID的场合URL改变视为新请求参数，不擅自去掉可能影响文件内容的查询参数。

客户端查询可指数退避并设上限，等待超时不自动重发创建。依赖重试只对暂时性错误进行，最多次数和执行截止时间配置化；业务错配、非法配置、结构化数据不合法不重试。取消后停止调度新子任务并禁止回写成功结果，临时产物清理不能删除已供其他任务使用的解析缓存。

## 六 合同验证用例

新四类型正常申请书正确分流；同一申请书跨阶段不串缓存；改文件名不能绕过正文错配；通用材料不误报另一业务；等待超时后保持同一错误详情；同request_id同输入返回同ID、不同输入409；车类录入两车输出一条公共信息和两条车辆记录；两证件分别匹配；缺号牌/冲突页待确认且不错误拆分；经办/机构同材料归并保留依据；OR/AND执行与四态汇总正确；取消与完成竞争不回写成功；结果多页固定快照且无遗漏/重复；网关10M限制无截断；预览图绑定原文件页码并检查授权。

## 七 拆页子任务契约

POST /api/v1/vehicle/tasks/{task_id}/split只允许引用已完成且用户可访问的vehicle_extraction父任务。父结果的车辆识别和页码映射作为不可变输入，拆分不会覆盖录入结果，也不会改变已发出的父结果分页游标。

| 入参 | 类型 | 约束 |
| --- | --- | --- |
| task_id | string，路径 | 父录入任务ID |
| request_id | string | 必填；拆分动作自己的幂等标识 |
| parent_result_version | string | 必填；与父任务结果版本一致，否则409 RESULT_VERSION_CONFLICT |
| file_ids | array<string>或null | 选填；仅父快照中允许按页拆分的PDF；空值代表全部适用证件PDF |
| vehicle_ids | array<string>或null | 选填；限父快照中已唯一识别号牌的车辆；空值代表全部可确定车辆 |

返回TaskAccepted，新增parent_task_id、parent_result_version，task_type=vehicle_split。GET /vehicle/tasks/{child_id}/result返回result_kind=vehicle_split、split_files[]、unresolved_pages[]和summary。每个unresolved_pages项有original_file_id、original_pages、candidate_vehicle_ids、reason；多号牌或无号牌页不自动跨车分配。新生成文件的文件名采用号牌加材料种类及去重序号，下载引用受任务权限控制。

同一父快照、同一拆页参数、同一request_id必须返回同一子任务；改变参数需新request_id。取消子任务只取消拆分页，不取消已完成的父录入任务。重新上传材料需新录入任务，旧拆分页仍指向旧原件。父录入结果不动态追加拆页文件；前端以vehicle_id关联子任务拆分结果，保证父结果版本稳定。

## 八 原生接口完整交互示例

以下全部是原生Agent统一外壳示例，HTTP成功和body.code均为200；不代表另外的中台外层封装。file_type中的vehicle_disposal_application、vehicle_disposal_list、vehicle_driving_license、vehicle_registration_certificate等是拟新增系统材料编码，非已有中台材料编码。示例省略部分材料只为说明结构，正式调用仍按规则检查完整材料。

### 录入创建与返回

```json
{
  "request_id": "veh_entry_20261104_001",
  "business_type": "机动车",
  "disposal_mode": "auction",
  "rule_config_id": "vehicle_auction_v1",
  "files": [
    {"file_id": "f01", "file_url": "https://example.invalid/files/app.pdf", "file_name": "车辆处置申请表.pdf", "file_type": "vehicle_disposal_application", "upload_stage": "entry"},
    {"file_id": "f02", "file_url": "https://example.invalid/files/list.pdf", "file_name": "车辆处置明细表.pdf", "file_type": "vehicle_disposal_list", "upload_stage": "entry"},
    {"file_id": "f03", "file_url": "https://example.invalid/files/licenses.pdf", "file_name": "行驶证合并.pdf", "file_type": "vehicle_driving_license", "upload_stage": "entry"}
  ]
}
```

```json
{
  "code": 200,
  "message": "success",
  "trace_id": "trace_vehicle_001",
  "timestamp": "2026-11-04T02:00:00Z",
  "data": {
    "request_id": "veh_entry_20261104_001",
    "task_id": "veh_entry_001",
    "task_type": "vehicle_extraction",
    "status": "pending",
    "created_at": "2026-11-04T02:00:00Z",
    "status_url": "/api/v1/vehicle/tasks/veh_entry_001",
    "materials_url": "/api/v1/vehicle/tasks/veh_entry_001/materials",
    "result_url": "/api/v1/vehicle/tasks/veh_entry_001/result"
  }
}
```

business_type=机动车、disposal_mode=auction/dismantling为本设计拟约定值，接口发布时与业务及平台共同固定，不属于现有四类BusinessType。样例中的域名不可实际访问。

### 附件匹配结果data

```json
{
  "task_id": "veh_entry_001",
  "ready": true,
  "items": [
    {"file_id": "f03", "file_name": "行驶证合并.pdf", "declared_file_type": "vehicle_driving_license", "detected_file_type": "vehicle_certificate", "material_subtype": "driving_license", "match_status": "matched", "reason": "正文识别为机动车行驶证", "sources": [{"page_number": 1, "source_content": "机动车行驶证"}]}
  ],
  "missing_materials": [{"material_code": "vehicle_registration_certificate", "reason": "适用规则要求登记证书但未匹配到"}],
  "unexpected_materials": [],
  "unrecognized_files": [],
  "merge_records": []
}
```

### 状态结果data

GET /api/v1/vehicle/tasks/veh_entry_001等价查询底层GET /api/v1/task/veh_entry_001?type=vehicle_extraction&include_details=false。

```json
{
  "task_id": "veh_entry_001",
  "task_type": "vehicle_extraction",
  "status": "processing",
  "stage": "extracting",
  "progress": 0.55,
  "status_message": "已完成11项处理，共20项",
  "total_count": 20,
  "completed_count": 11,
  "error_message": null,
  "error": null,
  "created_at": "2026-11-04T02:00:00Z",
  "updated_at": "2026-11-04T02:00:12Z",
  "completed_at": null
}
```

### 录入结果data节选

字段编码仅为结构示例。工程字段plate_number用于聚合实体；业务系统各车牌字段的正式编码仍从配置读取。

```json
{
  "task_id": "veh_entry_001",
  "task_type": "vehicle_extraction",
  "result_kind": "vehicle_extraction",
  "result_version": "r1",
  "business_type": "机动车",
  "disposal_mode": "auction",
  "rule_config_id": "vehicle_auction_v1",
  "rule_fingerprint": "sha256:example-rule",
  "common_fields": [],
  "vehicles": [
    {
      "vehicle_id": "v01",
      "plate_number": "京A12345",
      "plate_status": "identified",
      "fields": [
        {
          "field_id": "plate_v01",
          "field_name": "plate_number",
          "field_type": "text",
          "field_status": "success",
          "selected_value": "京A12345",
          "selected_source_file_id": "f02",
          "selection_reason": "按已确认的材料优先级选择",
          "priority_hint": "优先来源为车辆处置明细表",
          "values": [{"source_file_type": "vehicle_disposal_list", "source_file_name": "车辆处置明细表.pdf", "source_field_name": "号牌号码", "extracted_value": "京A12345", "extract_status": "success", "confidence": 0.98, "sources": [{"source_file_id": "f02", "source_file_type": "vehicle_disposal_list", "source_file_name": "车辆处置明细表.pdf", "source_field": "号牌号码", "source_content": "京A12345", "page_number": 1, "coordinates": {"x": 120, "y": 220, "width": 180, "height": 40}, "coordinate_space": "rendered_page_pixels", "page_width": 1240, "page_height": 1754, "confidence": 0.98, "trace_supported": true, "preview_image_url": "/api/v1/preview/files/highlights/veh_entry_001/f02_p1.jpg"}]}]
        }
      ]
    }
  ],
  "vehicle_statistics": {"baseline_file_ids": ["f02"], "baseline_record_count": 2, "extracted_vehicle_count": 2, "unique_plate_count": 2, "duplicate_plates": [], "unidentified_record_count": 0},
  "cross_file_checks": [{"file_id": "f03", "vehicle_count": 1, "missing_plates": ["京B23456"], "extra_plates": [], "consistency_status": "inconsistent"}],
  "next_cursor": "cursor-r1-v02",
  "has_more": true
}
```

### 助审创建与重触发

POST /api/v1/vehicle/audit/tasks，服务机构的新材料与经办旧材料分别保留上传阶段。重触发request_id必须为本轮新值，previous_task_id仅链接上一轮审查，不复用旧任务ID覆盖历史。

```json
{
  "request_id": "veh_audit_20261104_002",
  "business_type": "机动车",
  "disposal_mode": "auction",
  "extraction_task_id": "veh_entry_001",
  "previous_task_id": "veh_audit_001",
  "common_confirmed_fields": [],
  "vehicles": [{"vehicle_id": "v01", "plate_number": "京A12345", "confirmed_fields": [{"field_name": "plate_number", "field_value": "京A12345", "field_type": "text"}]}],
  "files": [{"file_id": "f10", "file_url": "https://example.invalid/files/agency-license.pdf", "file_name": "行驶证合并.pdf", "file_type": "vehicle_driving_license", "upload_stage": "review_agency"}]
}
```

初次助审省略previous_task_id。TaskAccepted返回新task_id=veh_audit_002。审核结果data节选如下，所有计数均针对完整任务；not_applicable不计入passed。

```json
{
  "task_id": "veh_audit_002",
  "task_type": "vehicle_audit",
  "result_kind": "vehicle_audit",
  "result_version": "r1",
  "vehicles": [{"vehicle_id": "v01", "plate_number": "京A12345", "audit_results": [
    {"audit_rule_id": "vehicle_plate_consistency", "audit_rule_name": "号牌一致性核对", "audit_status": "completed", "audit_result": "failed", "audit_explanation": "待审号牌京A12345与服务机构附件提取号牌京A12346不一致", "sources": [{"source_file_id": "f10", "source_file_name": "行驶证合并.pdf", "source_field": "号牌号码", "source_content": "京A12346", "page_number": 1, "preview_image_url": "/api/v1/preview/files/highlights/veh_audit_002/f10_p1.jpg", "trace_supported": true}]},
    {"audit_rule_id": "conditional_item", "audit_rule_name": "条件适用项", "audit_status": "completed", "audit_result": "not_applicable", "audit_explanation": null, "sources": []}
  ]}],
  "summary": {"total": 2, "passed": 0, "failed": 1, "pending": 0, "not_applicable": 1, "execution_failed": 0},
  "next_cursor": null,
  "has_more": false
}
```

实际failed/pending审核项必须填充真实sources；缺少附件的pending项可没有原文截图，但必须明确标记缺失材料及不能溯源的原因。示例条件适用项的具体免审条件由正式审核规则提供。

### 拆页创建与结果

POST /api/v1/vehicle/tasks/veh_entry_001/split：

```json
{"request_id": "veh_split_20261104_001", "parent_result_version": "r1", "file_ids": ["f03"], "vehicle_ids": ["v01"]}
```

TaskAccepted返回task_id=veh_split_001、task_type=vehicle_split、parent_task_id=veh_entry_001。完成后GET /api/v1/vehicle/tasks/veh_split_001/result的data为：

```json
{
  "task_id": "veh_split_001",
  "task_type": "vehicle_split",
  "result_kind": "vehicle_split",
  "result_version": "r1",
  "parent_task_id": "veh_entry_001",
  "parent_result_version": "r1",
  "split_files": [{"split_file_id": "sf01", "original_file_id": "f03", "vehicle_id": "v01", "plate_number": "京A12345", "original_pages": [1, 2], "file_name": "京A12345_行驶证_01.pdf", "download_url": "/api/v1/preview/files/vehicle/veh_split_001/sf01.pdf", "split_status": "success"}],
  "unresolved_pages": [],
  "summary": {"total_requested_vehicles": 1, "success_count": 1, "pending_count": 0, "failed_count": 0},
  "next_cursor": null,
  "has_more": false
}
```

### 取消复用

POST /api/v1/task/veh_split_001/cancel?type=vehicle_split，或车辆族别名POST /api/v1/vehicle/tasks/veh_split_001/cancel；两者调用相同取消逻辑。成功返回统一外壳data={"task_id":"veh_split_001","status":"cancelled"}。已完成父任务不能取消，取消拆分页不影响父任务；已取消任务不得被迟到的子调用结果覆盖为completed。

### 错配及超时后错误

```json
{
  "code": 400,
  "message": "Bad Request",
  "trace_id": "trace_property_001",
  "timestamp": "2026-11-04T02:00:00Z",
  "error": {
    "error_code": "BUSINESS_TYPE_MISMATCH",
    "error_message": "申请书业务类型与请求不一致",
    "retryable": false,
    "details": [{"field": "files[0]", "message": "申请书正文识别为企业增资", "file_id": "f01", "file_name": "申请书.pdf", "expected_business_type": "产权转让-预披露", "detected_business_category": "企业增资", "detected_disclosure_stage": null, "page_number": 1, "evidence": "企业增资信息披露申请书"}]
  }
}
```

若原创建调用已返回pending，后续GET /task/{id}?type=extraction响应HTTP200、code=200，data.status=failed、data.error为上例error对象，data.error_message为简短说明；禁止将error详情仅嵌入字符串。查询操作trace_id与原处理trace_id可不同，任务可增量保存processing_trace_id以关联原失败日志。

## 九 外层封装与原生外壳隔离

本次已检查的API DOCX第一章第1.1节和仓库原生接口采用数值code=200。仓库平台提供方适配仍保持该Body，只额外写入x-gw-biz-code（成功PS-001）与x-gw-biz-msg。若中台另有S2头部或成功码0000等封装，应由独立适配器执行明确转换：外层成功只代表网关/适配调用成功；内层task.status、字段状态和audit_result原样保留。不能全局把原生code改成字符串0000，也不能将PS-001、HTTP200、业务审核passed混成一层。S2字段定义与最终成功码应引用其正式规范，未提供明确定义时列为联调确认，不在本设计中假定已实现。

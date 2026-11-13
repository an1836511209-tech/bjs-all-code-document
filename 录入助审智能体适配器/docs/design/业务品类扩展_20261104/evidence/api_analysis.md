# 接口基线核对

核对日期：2026年11月4日。依据：用户2026年10月30日API DOCX抽取件 `api_reference.md` 第一章第1节；当前仓库代码；需规 `requirements.txt`。本文仅记录事实与建议，不表示接口已实现。

## 一 现有可复用接口

| 能力 | 智能体直接路径 | 当前主要契约 | 代码位置 |
| --- | --- | --- | --- |
| 文件质量检测 | POST /api/v1/file/quality-check | files[]；file_url/file_stream；每文件质量结论 | src/api/v1/endpoints/file.py:43；src/schemas/file.py:114 |
| 文件分类 | POST /api/v1/file/classification | files[]、request_id、task_id、timeout；支持等待超时后查询分类任务 | src/api/v1/endpoints/classification.py:33；src/schemas/classification.py:34 |
| 字段提取 | POST /api/v1/extraction/sync | extraction_type、files[]、rule_config_id、request_id、task_id、timeout；默认同步等待1000ms | src/api/v1/endpoints/extraction.py:37；src/schemas/extraction.py:24 |
| 规则审核 | POST /api/v1/audit/sync | audit_type、confirmed_fields[]、files[]、rule_config_id、request_id、task_id、timeout、trigger_type | src/api/v1/endpoints/audit.py:44；src/schemas/audit.py:32 |
| 任务状态及结果 | GET /api/v1/task/{task_id} | type=extraction/audit/classification；include_details=true返回result | src/api/v1/endpoints/task.py:24；src/schemas/task.py:38 |
| 任务取消 | POST /api/v1/task/{task_id}/cancel | 可选type；只允许pending/processing取消 | src/api/v1/endpoints/task.py:228 |
| 溯源文件预览 | GET /api/v1/preview/files/{file_path:path} | 返回文件流；PDF、图片等按扩展名确定Content-Type | src/api/v1/endpoints/preview.py:17 |
| 上传到Agent存储 | POST /api/v1/file/minio/upload | multipart/form-data；API DOCX第1节未列，代码已有 | src/api/v1/endpoints/minio_upload.py |

现有业务枚举只有四类实物，见 `src/schemas/rule_config.py:14`。请求中的业务类型虽然是str，但服务选择规则仍受映射约束，不能认为字符串入参天然支持新品类。

平台提供方另有适配路径，默认前缀 `/api/platform/v1`，可配置。质量、分类、上传、提取、审核路径后缀与直接接口一致；任务查询使用 `GET /api/platform/v1/task?task_id=...&type=...`，取消使用 `POST /api/platform/v1/task/cancel?task_id=...&type=...`。平台入口复用原endpoint，不复制业务逻辑；预览、规则配置CRUD/Web、Swagger不在该路由覆盖范围。依据 `src/platform_gw/router.py:27`、`config/platform_gw_config.py:23`及`:47`。

## 二 必须在新设计中说明的差异

| 对照项 | API DOCX | 当前代码 | 设计处理 |
| --- | --- | --- | --- |
| 文件分类 | 标注待更新；仅files/request_id与results/processing_time_ms | 还有task_id、timeout默认300000ms；响应status、任务ID与统计；支持classification查询取消 | 对外同步修订文档，不据旧说明删除代码能力 |
| 提取整体状态 | 表格含timeout | TaskExtractionStatus只有success/partial/pending/failed | 生命周期timeout仅由TaskStatus表达；等待1000ms超时返回pending，后台继续 |
| 任务类型 | 仅extraction/audit | 已含classification | 新契约须涵盖现有第三类任务 |
| 提取files必填 | 标为是 | 模型默认空列表，考虑审核复用场景 | 四个新增辅助录入场景要求申请书；在场景校验层拒绝缺失，不全局破坏旧审核链 |
| 确认字段field_type | 标为必填 | ConfirmedField默认text，可省略 | 保持兼容，新增场景建议显式传入 |
| 提取值类型 | String/Array | ExtractedFieldValue.extracted_value是Optional[Any] | 能承载JSON不等于已支持车辆明细整个链路；机动车需专用聚合模型 |
| 审核业务四态 | passed/failed/pending/manual_review | 与旧文档一致 | 机动车需规第四态是无需审核，新增not_applicable；禁止用manual_review冒充无需审核 |
| 错误示例 | COMMON_002；部分取消错误示例使用detail | 参数校验实际VALIDATION_ERROR；HTTP异常统一error外壳 | 保留现有统一外壳，修正文档示例；新增业务码清楚标识为项目约定 |
| 溯源 | 基础page/coordinates/regions | 还有trace_supported、document_type、sheet_name/index/cell_refs | 增量保留；车辆补充file_id、vehicle_id和原始页映射 |

## 三 状态与幂等现状

生命周期 `pending → processing → completed/failed/timeout/cancelled` 与业务结果必须分开。提取同步返回的data.status是success/partial/pending/failed；审核同步返回processing或completed；任务查询的data.status是TaskStatus。`completed`不表示审核通过；`pending`在提取结果中也可表示所有字段均待确认，因此客户端以任务查询生命周期判断是否继续轮询。

当前任务ID生成优先级为task_id、request_id、随机ID，并添加extraction_/audit_/classification_内部前缀，对外通常去前缀。查询未传type时依次查三种前缀，同名任务可能歧义，新客户端必须传type。依据 `src/api/v1/utils/task_handler.py:18`、`:136`、`:144`。

当前提取/审核/分类仅在同ID正在执行时返回现有占位响应，没有比较请求内容指纹；同ID已完成任务可被reset_if_exists=True重置。不能将现状描述为跨请求全生命周期严格幂等。新增任务需保存请求指纹：同ID同指纹复用，同ID不同指纹返回409；重新审核以新任务ID关联历史任务，避免覆盖证据。

取消通过Redis任务状态和通知阻止后续执行，属于协作式取消。TaskStore.update_task会防止取消结果被普通更新覆盖（`src/services/task_store.py:266`）；已发出的外部OCR/LLM调用未必能立即终止，不能承诺即时硬取消。

## 四 错误与网关落点

`src/schemas/base.py:42`的ErrorDetail只有field和message；Task和TaskStatusData仅有error_message。新增材料错配错误需增加可选结构化error/details并完成Redis序列化、更新及查询透传。`src/main.py:318`HTTP异常包装当前提取error_code/error_message但不保留details，trace_id也未统一放在响应顶层。提取、审核、分类路由通用except又可能将新业务异常转成500；须增加业务异常分支后再接通契约。

平台只写x-gw-biz-code/x-gw-biz-msg，不应伪造x-gw-instance/x-gw-return-code/x-gw-return-msg。现有成功PS-001，超限PI-001；其余子码是本项目约定，新增错配/冲突/未就绪等要纳入 `src/platform_gw/mapping.py`，未映射当前会落到PO-001，不能直接假设已定义。平台JSON响应默认阈值为10×1024×1024字节、未压缩UTF-8体积，代码也注明平台最终口径待书面确认。超限整体替换413错误，不能靠截断JSON。机动车结果应分页，证据图和拆分PDF返回引用，避免超限。

鉴权不能据现有代码宣称已具备完整用户级权限。平台提供方API Key是可选配置，x-gw-appid/x-gw-org只用于观测不据此赋权；直接预览当前为MinIO对象代理且Cache-Control为public。目标设计应把真实调用主体、任务/文件访问范围及鉴权覆盖明确到部署集成，新增预览建议使用经授权的受控入口并调整缓存策略。

## 五 范围边界与确认事项

需规四个产权增资场景明确为辅助录入，共用创建/状态/结果接口，不应把仓库已有开发草案中的产权增资审核自动纳入本次必交范围。机动车要求独立的附件匹配结果视图、公共任务信息加多车辆结果、拆分文件及审核四态；这些均非旧平面字段接口已实现能力。

API DOCX第一章第2节的一句话找项目、会话重生成、删除记录、标题总结与本次扩品类无直接关系，不属于本次设计变更。

联调前须确认：机动车外部业务枚举与解体/拍卖参数；新增材料类型及中台编码；字段字典及正式字段编码；结果分页大小和峰值载荷；鉴权主体及权限来源；平台10M字节口径及新增子码；统一UTC带时区时间输出；新任务结果保存期和拆分文件保存期。

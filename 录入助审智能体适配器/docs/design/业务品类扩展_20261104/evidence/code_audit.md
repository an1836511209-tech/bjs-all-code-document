# 业务品类扩展：代码现状审查

审查日期：2026-11-04。方式：静态只读审查，未启动外部 OCR、LLM、Redis 或 MinIO 服务；未执行功能测试。本文件只区分“代码事实”与“扩展建议”，不将建议认定为已实现。

## 1. 项目形态与真实边界

| 内容 | 代码事实 | 证据（仓库相对路径与行号） |
|---|---|---|
| 应用入口 | FastAPI 单体服务；Python 依赖声明为 3.10+，Pydantic 2；主应用挂载 v1、规则 Web 与平台适配路由 | `src/main.py:402`、`:404`、`:412`；`pyproject.toml:17` |
| 原生 API | 聚合前缀 `/api/v1` | `src/api/v1/__init__.py:20` |
| 智能处理 API | 质量检测 POST `/file/quality-check`；分类 POST `/file/classification`；提取 POST `/extraction/sync`；审核 POST `/audit/sync` | `src/api/v1/endpoints/file.py:43`、`:47`；`classification.py:30`、`:34`；`extraction.py:26`、`:38`；`audit.py:33`、`:45` |
| 任务 API | GET `/task/{task_id}`；POST `/task/{task_id}/cancel` | `src/api/v1/endpoints/task.py:17`、`:25`、`:229` |
| 文件与配置 API | MinIO 上传、预览代理、规则 CRUD 与 Web 页均已挂载；规则配置 Web 不等于业务录入前端 | `src/api/v1/__init__.py:23`；`src/api/v1/endpoints/minio_upload.py:38`；`preview.py:17`；`rule_config.py:29`；`rule_config_web.py:32` |
| 平台 API | 默认前缀 `/api/platform/v1`，复用同一 endpoint；任务查询/取消改为 query 参数形式 `/task`、`/task/cancel` | `config/platform_gw_config.py:26`；`src/platform_gw/router.py:27`、`:83`、`:103` |
| 数据保存 | 任务/结果用 Redis；解析缓存用本地 JSON；规则用本地 JSON；预览/文件用 MinIO。虽然依赖中有 SQLAlchemy、Alembic、Celery，但未在 `src`/`config` 找到启用的关系库模型/迁移/Celery任务实现 | `src/services/task_store.py:34`；`src/services/storage/cache_service.py:36`；`src/services/rule_config_service.py:34`；`src/utils/minio/client.py` |

README 声称存在流式接口、JWT 和部分旧解析路线，不能直接等同于当前实现：本轮检索到的提取/审核路由均为 `/sync`；`src/main.py:250` 仍标注 JWT 开发中。概要设计应以实际路由和模型为现状基线。

## 2. 业务分类与材料体系

`BusinessType` 仅有“有纸大宗实物、无纸大宗实物、有纸小宗实物、无纸小宗实物”（`src/schemas/rule_config.py:14`）；`EXTRACTION_TYPE_TO_BUSINESS_TYPE` 同样只映射这四种（`src/utils/extraction_type_mapper.py:15`）。尚无产权转让、企业增资、机动车独立业务定义。

`FileType` 当前共 22 种（`src/schemas/file.py:15`），包括申请书、评估/备案、内部决议、营业执照、资产清单、车辆证书等，但无审计报告、财务报表、企业章程等新业务专属材料枚举。`vehicle_certificate` 已存在不代表机动车完整业务流程已实现。

现有规则文件：

| 文件 | 业务 | 版本 | 提取规则数 | 审核规则数 |
|---|---|---|---:|---:|
| `data/rule_configs/7c2f409d-86ac-4e1d-a26b-4b9fe72cfd77.json` | 有纸大宗实物 | 1.1.0 | 82 | 81 |
| `data/rule_configs/30875937-54f1-489d-b5fa-a5f164f129c4.json` | 无纸大宗实物 | 1.1.0 | 82 | 81 |
| `data/rule_configs/365f6bb9-e66c-4eda-8e34-b8f7d8979981.json` | 有纸小宗实物 | 1.0.0 | 48 | 50 |
| `data/rule_configs/f05a71e3-b4b7-4d46-a547-50256fa7982d.json` | 无纸小宗实物 | 1.0.0 | 49 | 56 |

两个分类实现并存，扩展材料时必须同步处理或抽出统一注册表：

- 内部审核使用 `src/services/classification_service.py:16` 的中台代码直接映射、文件名关键词、LLM 兜底；`:20` 有代码映射，`:38` 明确 `ZRFZC`（转让方章程）暂不映射。
- 对外分类使用 `src/services/classification/service.py:40` 的另一份材料关键词表；`:182` 类说明明确与内部服务分离；`:191` 仅取前两页，`:194` 最长 10,000 字符。
- `src/utils/material_resolver.py:56` 从枚举标签与文件名建立标准材料名称映射，匹配粒度是 `file_type`，无主体/报告期维度。

## 3. 提取、溯源与审核能力

### 已实现

提取输入 `ExtractionRequest` 含 `extraction_type`、`files`、`rule_config_id`、`timeout`、`request_id`（`src/schemas/extraction.py:24`）。文件输入类型是严格 `FileType` 枚举（`:15`）；审核文件输入则允许任意字符串类型以兼容中台代码（`src/schemas/audit.py:16`）。

提取规则支持文本、单选、多选，材料参考、自然语言提取逻辑、字典 API 与选项（`src/schemas/rule_config.py:22`、`:82`）。审核规则支持字段审核/文件审核、自动或手工映射、简单比较、材料缺失自动通过开关、主文件类型（`:158`）。缺失材料自动通过是已有配置能力，新品类不应无条件继承该开关。

实际解析路线：Word → Gotenberg 转 PDF → Paddle OCR，配置允许降级 MinerU（`src/services/extraction/service.py:1390`、`:1419`）；Excel 使用 openpyxl 生成 Anchor Markdown，可溯源到 sheet/cell（`:1456`）；纯文本等走 Tika，不支持坐标溯源（`:1500`）；图片转 PDF 后 Paddle（`:1547`）；PDF 优先 Paddle，失败后按配置 MinerU（`:1586`）。因此不能根据 README 写成“Word 一律 Tika、无溯源”。

溯源模型已含原文件名/类型、原文、预览图片、页码、坐标、置信度、跨页信息、Excel 单元格与多区域（`src/schemas/extraction.py:86`、`:95`）。任务提取整体结果为 `success/partial/pending/failed`；单字段为 `success/pending/failed`（`:67`、`:74`）。多来源不一致有 `inconsistent_values`（`:158`）。

审核结果模型支持 `passed/failed/pending/manual_review`（`src/schemas/audit.py:99`）。文件审核按要点输出明细（`:129`）；未被自动审核规则覆盖的确认字段会补充人工审核项（`src/services/audit/service.py:1963`）。

### 多实体适配限制

1. `src/utils/field_value_converter.py:14` 只将 `ZRF` 认作需要展开的嵌套字段；`:144` 对对象数组仅展开首元素，重复主体无法保持独立审核语境。
2. `src/services/extraction/service.py:753` 解析结果按 `file_type` 分组，`:837` 将同类型多个文件合并 Markdown/页码。保留文件名列表和部分溯源信息，但没有显式的材料所属主体、报告年度、车辆 ID。
3. `src/services/audit/service.py:814` 将字段值转为 `field_name → source_file_type → value`，`:844` 对同类型后续值覆盖先前值。仅添加股东/转让方数组字段并不能安全实现多实体。

**设计建议**：为提取、确认、审核、溯源统一引入业务对象路径与稳定行 ID，例如 `(entity_type, entity_id, field_code, period)`；材料持有主体角色、主体 ID、报告期和材料版本；同类文件只在同一实体/期间内合并；按实体运行和统计规则，保留原始多来源列表。

## 4. 任务模型、异步与持久化

任务类型有 `extraction/audit/classification`；任务状态有 `pending/processing/completed/failed/timeout/cancelled`（`src/schemas/task.py:15`、`:22`）。这是执行状态，与提取成功、审核通过等业务结论应分开解释。

endpoint 在调用服务前创建任务，再用 `asyncio.create_task` 在应用进程内执行（`src/api/v1/endpoints/extraction.py:145`、`:159`；`classification.py:132`、`:147`）。`src/api/v1/utils/task_handler.py:68` 使用 `asyncio.wait`，等待窗口到期返回 pending，后台继续执行；默认提取/审核 1 秒，分类 300 秒（`src/schemas/extraction.py:30`、`src/schemas/audit.py:39`、`src/api/v1/endpoints/classification.py:103`）。同步等待超时并不等同于任务状态 `timeout`。

任务内部 ID 为“任务类型前缀 + task_id/request_id/随机ID”，对外去掉前缀（`src/api/v1/utils/task_handler.py:19`、`:121`）；不指定 type 查询时按 extraction、audit、classification 顺序查找（`:129`）。接入方应显式携带 type，避免同 request_id 跨任务查询歧义。

Redis 任务数据 TTL 默认配置约 90 天，启动每天清理 90 天前任务（`src/services/task_store.py:41`；`src/main.py:156`）。取消写状态并发布 `cancel:task`，节点订阅后取消本地工作（`src/services/task_store.py:350`、`:378`；`src/main.py:147`）。进程中断后 Redis 中的执行状态不会自动让 Python 协程恢复；没有持久化任务队列即不能声称故障后自动断点续跑。

现有 endpoint 对 pending/processing 重复请求跳过，但 completed 可以重置重跑（`src/api/v1/endpoints/extraction.py:89`、`:145`）；查任务与新建并非一个 Redis 原子操作（`src/services/task_store.py:138`、`:192`）。提取服务有文件哈希分布式锁，但只在 `not request.task_id` 时获取（`src/services/extraction/service.py:456`），标准 endpoint 已注入 task_id，不能据此声称所有 API 请求有严格跨节点幂等。

**设计建议**：请求键关联规范化请求摘要，首次受理使用 Redis 原子 SETNX/Lua；同键异参返回明确冲突，同键同参返回原任务；任务快照固定规则版本、字段/材料字典版本与算法版本。若期望节点故障恢复，需要持久化队列、租约/心跳、尝试次数、幂等分阶段检查点，并作为新增能力说明。

## 5. 缓存隔离：必须优先修正

`src/utils/file_hash.py:132` 明确 `extraction_type` 和 `rule_config_id` 不参与 hash；`:156` 只收集附件内容 MD5，排序后 SHA256。任务缓存索引键为 `cache:hash:{files_hash}`（`src/services/task_store.py:51`）。提取服务在加载规则配置前即可命中并直接返回历史完整提取结果（`src/services/extraction/service.py:374`、`:447`；配置加载在 `:546`）。审核复用提取缓存也仅按 files_hash（`src/services/audit/service.py:739`）。

当前可缓存阈值是 `success_count + pending_count > failed_count`（`src/utils/cache_policy.py:74`），并非必须所有字段成功。不能将“缓存命中”写成“已验证匹配当前业务规则”。

**设计建议**：

- 文件解析缓存键：文件内容 hash + 解析器/转换器版本 + 解析选项；可以在授权范围内复用。
- 业务提取结果缓存键：机构/项目隔离范围 + 业务类型/模式 + 附件 hash 与角色归属/报告期 + 规则发布 ID/hash + 字段字典版本 + 模型/提示词版本。
- 审核结果还应纳入用户确认字段摘要和审核规则版本。
- 发布时切换 namespace，旧缓存只能在完全相同快照条件下读取。

## 6. 规则管理、网关与部署注意点

规则直接写本地 JSON（`src/services/rule_config_service.py:64`），默认选择同业务类型、enabled=true、更新时间最近的配置（`:180`），`version` 是字符串元数据（`src/schemas/rule_config.py:297`），未实现不可变发布、审批、灰度或任务固定版本。多副本下规则目录与本地解析缓存必须共享/一致分发，否则 Redis 中任务可能指向另一节点不可见的解析缓存键。

平台提供方设置 `x-gw-biz-code/x-gw-biz-msg`，不得伪造平台生成的 `x-gw-instance/x-gw-return-code/x-gw-return-msg`（`src/platform_gw/constants.py:3`）。中间件只作用于显式白名单；规则 CRUD、规则 Web、预览等不在平台路由范围（`src/platform_gw/router.py:1`）。提供方可选 API key 校验已经实现，但是否启用取决于部署配置；`x-gw-*` 输入头不据此赋权（`src/platform_gw/middleware.py:53`、`:66`）。需确认内部管理入口访问控制和业务平台/中台的权限责任。

原生参数校验错误统一为 HTTP 400 `VALIDATION_ERROR`；HTTP 错误规范化；未捕获错误为 HTTP 500 `INTERNAL_ERROR`（`src/main.py:287`、`:317`、`:349`）。业务字段审核不通过应保留成功的 HTTP 响应和审核结论，不与技术异常混用。

限流使用进程内 `asyncio.Semaphore`（`src/api/v1/middleware/rate_limiter.py:19`、`:25`），不是跨所有 worker/节点的全局上限。扩展财务大表/多主体/多车辆时应分别控制任务、文件 OCR、LLM 子任务并发，并用压测基线确定容量；不能由依赖库或现有配置推导已满足生产 SLA。

## 7. 推荐设计中的代码改动清单（均为拟新增/改造）

| 层 | 主要改动位置 | 设计方向 |
|---|---|---|
| 业务与材料模型 | `src/schemas/rule_config.py`、`src/schemas/file.py`、`src/utils/extraction_type_mapper.py` | 增加三品类/模式、材料注册和别名；保留旧枚举兼容 |
| 接入模型 | `src/schemas/extraction.py`、`src/schemas/audit.py`、`src/schemas/classification.py` | 增加可选上下文、实体归属、稳定字段路径；版本化规范必填语义 |
| 分类与材料解析 | 两个 classification service、`src/utils/material_resolver.py` | 用统一目录驱动代码映射/别名/分类提示词，避免产权证与产权交易材料误配 |
| 多实体提取/审核 | `src/services/extraction/service.py`、`src/services/audit/service.py`、`src/utils/field_value_converter.py` | 去除首条展开和按类型单值覆盖；按主体/报告期分组 |
| 确定性审核 | 审核服务内可抽独立计算器 | 金额/比例/日期/汇总用 Decimal 与结构化运算，LLM 负责材料语义和证据定位 |
| 规则发布 | `src/services/rule_config_service.py` 与规则存储层 | 不可变版本、显式发布指针、依赖校验、回滚、任务快照 |
| 缓存与幂等 | `src/utils/file_hash.py`、`src/services/task_store.py`、任务工具 | 解析/提取/审核分级键；原子受理；机构/项目隔离；规则版本隔离 |
| 网关与契约 | `src/platform_gw/*`、API文档和示例 | 保持原生/平台路径及任务语义明确；扩展响应仍受平台载荷上限约束 |



# 北交所 API 统一管控平台 — 服务提供方接入说明

> 文档日期：2026-09-06  
> 角色：**服务提供方**（本系统向平台发布接口，供其他系统经平台调用）  
> 规范依据：已读取并对照  
> - `北交所API统一管控平台-接口发布规范V0.5.docx`  
> - `API统一管控平台服务规范模板.docx`  
> - 工作表 `北交所API统一管控平台-接口发布规范V0.5.xlsx`  
> **本说明仅描述本地适配实现，不等于已通过平台接入验收。**

---

## 1. 改造方案摘要

| 项 | 说明 |
|---|---|
| 技术栈 | FastAPI + ASGI Middleware |
| 接入方式 | **隔离前缀** `/api/platform/v1`，复用现有业务 endpoint，不改 `/api/v1` 旧路径行为 |
| 适配机制 | `PlatformGwMiddleware` + 白名单 + 集中业务码映射；非逐接口复制包装 |
| Body | 保持原有 `code/message/data` 或 `error` 结构，**不**新增统一外壳，**不**把五字段塞进 Body |
| 响应头 | 仅设置提供方 `x-gw-biz-code` / `x-gw-biz-msg`；**不伪造**平台 `x-gw-instance` / `x-gw-return-code` / `x-gw-return-msg` |

---

## 2. 接口纳入 / 未纳入清单

### 2.1 已纳入（平台入口路径）

相对前缀：`/api/platform/v1`（与旧路径 `/api/v1/...` 业务语义一致，Body/方法复用）。

| 平台 HTTP 路径 | 方法 | 复用的业务函数 | 纳入理由 |
|---|---|---|---|
| `/file/quality-check` | POST | `check_file_quality` | 核心助审流水线；系统间可调用 |
| `/file/classification` | POST | `classify_files` | 核心分类能力；系统间可调用 |
| `/file/minio/upload` | POST | `minio_upload` | 文档明确“对方推送文件”；系统间接口证据最强 |
| `/extraction/sync` | POST | `extract_fields_sync` | 核心字段提取（同步 JSON） |
| `/audit/sync` | POST | `audit_fields_sync` | 核心规则审核（同步 JSON） |
| `/task` | GET | `get_task_status` | 同步超时后的任务查询配套；`task_id` 走 query |
| `/task/cancel` | POST | `cancel_task` | 任务取消配套；`task_id` 走 query |

白名单配置：`config/platform_gw_config.py` → `PLATFORM_GW_INCLUDED_PATHS`。

### 2.2 未纳入及理由

| 路径/能力 | 理由 |
|---|---|
| `/api/v1/**` 全部原路径 | 旧调用方兼容；平台入口独立，避免给旧调用方强加 Header/超限替换 |
| `/rule-configs/**`、规则配置 Web UI | 管理/运维界面，非系统间发布接口 |
| `/preview/**`、文件预览 GET | 浏览器/前端流式或二进制代理，不适配普通 JSON 发布模型 |
| SSE / stream 提取或审核 | 当前代码库同步接口为主；流式属特殊协议，平台场景未确认 |
| `/`、`/health`、`/docs`、`/redoc` | 探活与文档，非业务发布范围 |
| 静态资源 `/static` | 前端资源 |

**待产品/平台确认是否追加纳入的候选：** 规则配置只读查询、异步任务创建类接口（若存在独立异步入口）。

---

## 3. 业务码映射表

### 3.1 平台规范类别（V0.5 §5.2）

| 前缀 | 含义 | 说明 |
|---|---|---|
| PS | 业务成功 | **仅 PS-001 表示成功** |
| PV | 业务校验失败 | |
| PA | 提供方认证/权限失败 | |
| PI | 提供方内部异常 | **PI-001 专用于查询结果 >10M** |
| PO | 其他未归类 | |

### 3.2 本项目约定子码（非平台统一定义）

| 原业务码 / 场景 | 平台业务码 | 对外描述（中文，完整版在 Body/日志） | Header ASCII（默认模式） |
|---|---|---|---|
| 业务成功 `code=200` 且无 error | PS-001 | 业务处理成功 / Body.message | Business processed successfully |
| `VALIDATION_ERROR` | PV-001 | 请求参数验证失败 \| 字段详情 | Request parameter validation failed |
| `FILE_001` | PV-002 | 文件不能为空 | File must not be empty |
| `FILE_002` | PV-003 | 文件过大 | File size exceeds limit |
| `FILE_003` | PV-004 | 不支持的扩展名 | Unsupported file extension |
| `AUTH_REQUIRED` / 缺提供方密钥 | PA-001 | 提供方认证失败：缺少访问凭证 | Provider authentication required |
| `AUTH_INVALID` | PA-002 | 提供方认证失败：访问凭证无效 | Provider authentication failed |
| `PERMISSION_DENIED` / HTTP 403 | PA-003 | 提供方权限不足 | Provider permission denied |
| 响应 UTF-8 字节 > 阈值 | **PI-001** | 查询结果大于10M，请缩小查询区间或范围再执行查询 | Query result exceeds 10M; ... |
| `INTERNAL_ERROR` / 未捕获异常 | PI-002 | 服务器内部错误，请稍后重试 | Provider internal error |
| `HTTP_ERROR`（如 404） | PI-003 | 提供方处理失败 / detail | Provider HTTP error |
| `FILE_005` | PI-004 | 写入对象存储失败 | Object storage write failed |
| 未映射的业务失败码 | PO-001 | 未映射的业务失败 \| 原码信息 | Unmapped business failure |
| 其它未归类 | PO-002 | 未归类异常 | Unclassified provider exception |

映射实现：`src/platform_gw/mapping.py`。

**规则：** 不允许只根据 HTTP 200 判成功；HTTP 200 + 业务失败 → 失败码；未知失败 → PO-001，**绝不**默认 PS-001。

---

## 4. HTTP 状态码与 Header

### 4.1 三层含义

1. **HTTP status**：本应用既有语义（200/400/401/404/413/500…）默认保持。  
2. **平台码** `x-gw-return-*`：仅平台生成。  
3. **业务码** `x-gw-biz-*`：提供方生成。

### 4.2 与“非 200 归 D 类”的冲突（保持现状，待平台确认）

| 现状 | 影响 | 当前策略 |
|---|---|---|
| 参数错误 HTTP 400 | 平台可能归为 D 类提供方异常 | **保持 400**，业务头 PV-* |
| 认证失败 HTTP 401 | 同上 | **保持 401**，业务头 PA-* |
| 任务不存在 HTTP 404 | 同上 | **保持 404**，业务头 PI-003 |
| 报文超限 HTTP 413 | 同上 | **保持 413**，业务头 PI-001 |
| 内部错误 HTTP 500 | 同上 | **保持 500**，业务头 PI-002 |

**禁止**擅自把所有失败改成 HTTP 200。是否改为“业务失败也 200”需平台书面确认后再定向调整。

### 4.3 Header 中文编码（待联调）

- 规范要求报文 UTF-8，但**未明确**中文写入 HTTP Header 的线上编码。  
- 默认 `PLATFORM_GW_HEADER_MSG_MODE=ascii_fallback`：Header 使用 ASCII 安全描述；完整中文在 Body / 内部日志。  
- **不得**声称已完全符合中文 Header 描述要求。  
- 实验开关 `utf8_raw` 仅供联调，不作规范宣称。  
- 已处理 CR/LF 头注入，并按 UTF-8 字节截断校验（临时按 500 字节口径，`PLATFORM_GW_BIZ_MSG_MAX_BYTES`）。

---

## 5. 请求头与鉴权边界

平台标准请求头（消费方 ↔ 平台，**提供方不重复实现 Token/HmacSM3**）：

`x-gw-appid` / `x-gw-org` / `x-gw-token` / `x-gw-salt-key` / `x-gw-route` 等。

本系统：

1. **不**因带有 `x-gw-appid`/`x-gw-org` 而信任或赋权。  
2. 现网 `/api/v1` 尚无应用层 JWT（文档标注开发中）；平台入口可选启用提供方密钥：  
   - 环境变量 `PLATFORM_GW_PROVIDER_API_KEY`  
   - 请求头 `X-Provider-Api-Key`（**本项目约定**，非平台标准头）  
3. 不记录 Token/签名/密钥内容。  
4. **不为适配放开 CORS**；现有 CORS 配置未因本改造扩大。  
5. 平台到提供方的 IP 白名单 / mTLS 等属部署侧，**待确认**。

---

## 6. 报文大小

| 项 | 临时假设（可配置） |
|---|---|
| 阈值 | `PLATFORM_GW_MAX_PAYLOAD_BYTES` 默认 `10485760`（10MiB） |
| 口径 | 最终序列化后的 **UTF-8 字节**，未压缩 |
| 超限 | 不截断 JSON；整体替换为错误 Body + **PI-001**；不伪造平台码 R-004 |
| 上传 | multipart 仍由业务层 `MAX_FILE_SIZE`（200MB）约束；平台 10M 主要约束 JSON 交互报文，大文件场景需平台确认是否走 MFT 等 |

---

## 7. 调用示例

### 7.1 直连提供方（可本地验证两个业务头）

```http
POST /api/platform/v1/extraction/sync HTTP/1.1
Host: <provider-host>:8580
Content-Type: application/json

{"extraction_type":"...","files":[...], ...}
```

预期响应头（直连时**没有**平台三头属正常）：

```http
HTTP/1.1 200 OK
x-gw-biz-code: PS-001
x-gw-biz-msg: Business processed successfully
Content-Type: application/json
```

Body 仍为原结构，例如：

```json
{
  "code": 200,
  "message": "success",
  "trace_id": "trace_...",
  "timestamp": "...",
  "data": { }
}
```

参数校验失败示例：

```http
HTTP/1.1 400 Bad Request
x-gw-biz-code: PV-001
x-gw-biz-msg: Request parameter validation failed
```

### 7.2 经平台调用（尚未联调，不能写成测试通过）

预期消费方可见五个响应头：

| Header | 来源 | 联调检查 |
|---|---|---|
| `x-gw-instance` | 平台 | 非空、提供方未伪造 |
| `x-gw-return-code` | 平台 | 平台处理码 |
| `x-gw-return-msg` | 平台 | 平台描述 |
| `x-gw-biz-code` | 提供方透传？ | 是否原样到达消费方 |
| `x-gw-biz-msg` | 提供方透传？ | 中文编码是否保留；非 200 时是否仍透传 |

联调检查项：

1. 平台是否透传上游非 200 的 HTTP status / Body / 业务头。  
2. 中文 `x-gw-biz-msg` 编码方式。  
3. 提供方侧 IP 白名单与平台出口 IP。  
4. 是否要求提供方校验 `x-gw-*` 请求头（当前不校验、不赋权）。

---

## 8. 服务规范草稿（纳入接口）

> 系统编码 / 组织编码 / 五位服务序号：**待分配**（不编造）。  
> 服务标识格式：`API_<一级待分配>_<二级待分配>_<组织待分配>_<五位序号待分配>`  
> 服务中文名：动作词开头 + “服务”；英文名：Inquiry/Create/... + `Srv`。

### 8.1 检测文件质量服务

| 字段 | 值 |
|---|---|
| 服务标识 | API_待分配_待分配_待分配_待分配 |
| 中文名 | 检测文件质量服务 |
| 英文名 | ValidateFileQualitySrv |
| 版本 | 1.0 |
| 提供方代码/名称 | 待分配 / 北交所录入助审系统 |
| 提供方接口路径 | `/api/platform/v1/file/quality-check` |
| 方法 | POST |
| 实现方式 | Restful |
| 读写 | 读（检测，不落业务库主数据） |
| 同步异步 | 同步 |
| 业务规则 | 对附件做清晰度/分辨率/遮挡等质量检测；支持 URL 或 Base64 |
| 错误处理 | PV 参数校验；PI 内部异常；保持原 HTTP 状态 |
| 分页 | 无 |
| 数据量 | 单次 JSON ≤10M（临时）；大文件内容建议 URL 引用 |
| 安全 | 平台 Token；可选 `PLATFORM_GW_PROVIDER_API_KEY`；不信任 x-gw-appid 赋权 |
| 性能 | 待验证 |

### 8.2 分类文件类型服务

| 字段 | 值 |
|---|---|
| 中文名 | 分类文件类型服务 |
| 英文名 | InquiryFileClassificationSrv |
| 路径 | `/api/platform/v1/file/classification` |
| 方法 | POST |
| 同步异步 | 同步 |
| 业务规则 | LLM/规则对上传文件智能分类，返回 file_type 枚举 |
| 其余 | 同 8.1 安全/数据量口径；标识待分配 |

### 8.3 导入文件到对象存储服务

| 字段 | 值 |
|---|---|
| 中文名 | 导入文件到对象存储服务 |
| 英文名 | ImportFileToObjectStorageSrv |
| 路径 | `/api/platform/v1/file/minio/upload` |
| 方法 | POST（multipart） |
| 同步异步 | 同步 |
| 业务规则 | 接收文件流写入 Agent MinIO，返回 url/file_url/object_key |
| 限制 | multipart/二进制，不套用 JSON 包装；单文件业务上限 200MB；与平台 10M JSON 口径关系**待确认** |
| 自评：协议 | 特殊接口，平台是否支持 multipart **待确认** |

### 8.4 提取字段信息服务

| 字段 | 值 |
|---|---|
| 中文名 | 提取字段信息服务 |
| 英文名 | InquiryFieldExtractionSrv |
| 路径 | `/api/platform/v1/extraction/sync` |
| 方法 | POST |
| 同步异步 | 同步（超时返回 task 供查询） |
| 业务规则 | 多附件字段提取、溯源、高亮；可返回 pending+task_id |
| 数据量 | 结果超 10M → PI-001；建议缩小附件集或分页/拆分任务 |

### 8.5 审核字段规则服务

| 字段 | 值 |
|---|---|
| 中文名 | 审核字段规则服务 |
| 英文名 | ValidateFieldAuditSrv |
| 路径 | `/api/platform/v1/audit/sync` |
| 方法 | POST |
| 同步异步 | 同步（超时返回 task） |
| 业务规则 | 对确认字段与附件执行规则审核并汇总 |

### 8.6 查询任务状态服务

| 字段 | 值 |
|---|---|
| 中文名 | 查询任务状态服务 |
| 英文名 | InquiryTaskStatusSrv |
| 路径 | `/api/platform/v1/task` |
| 方法 | GET |
| 同步异步 | 同步 |
| 业务规则 | 查询 extraction/audit 任务进度与结果；`task_id` 必填 query；type 可选 |

### 8.7 取消任务服务

| 字段 | 值 |
|---|---|
| 中文名 | 取消任务服务 |
| 英文名 | UpdateTaskCancelSrv |
| 路径 | `/api/platform/v1/task/cancel` |
| 方法 | POST |
| 同步异步 | 同步 |
| 业务规则 | `task_id` 必填 query；仅 pending/processing 可取消 |

---

## 9. 自评清单

| 维度 | 结论 |
|---|---|
| 接口复用性 | 通过委托原 endpoint 复用业务层，无复制业务逻辑 |
| 协议 / 同步异步 | 以同步 Restful JSON 为主；multipart 上传单独标注；SSE 未纳入 |
| 异常响应 | 校验/认证/内部/未映射均映射到 PV/PA/PI/PO；敏感信息不外泄 |
| 需求合理性 | 隔离前缀降低对旧调用方影响；范围显式白名单 |
| 定义合规性 | 业务头在 Header；不伪造平台头；PI-001 保留给 10M |
| 业务粒度 | 按现有助审能力边界，未拆过细也未打包无关管理接口 |
| 参数完整性 | 与旧接口一致；服务规范字段待与消费方再核对 |
| 版本 | 初版 1.0；V0.5 允许多主版本并存，检查表倾向单主版本——**不自动下线旧 `/api/v1`** |
| 性能 | 中间件对 JSON 响应有缓冲；损耗**待验证**；超限有界缓冲 |
| 安全 | 不信任网关头赋权；可选提供方 API Key；不记密钥 |
| 稳定性 | 未纳入路径行为不变；应用外网关/容器错误无法补头（边界已明确） |

### 资料差异记录

- 检查表部分章节号过时；V0.5 对应第 4 章、第 5.2 节。  
- V0.5 允许多主版本并存；检查表原则上单主版本——多版本需评估旧版下线时间，**不得自动下线**。  
- V0.5 提到 PATCH；当前模板方法选项未列 PATCH——本批接口未使用 PATCH。  
- 性能损耗、可用性、评审结果：**待验证 / 待评审**（不照抄模板示例）。

---

## 10. 部署、回滚与开关

| 配置项 | 默认 | 说明 |
|---|---|---|
| `PLATFORM_GW_ENABLED` | true | false 时不注册平台路由（见 main）；中间件 enabled 亦可关 |
| `PLATFORM_GW_PREFIX` | `/api/platform/v1` | 隔离前缀 |
| `PLATFORM_GW_MAX_PAYLOAD_BYTES` | 10485760 | 10MiB 临时假设 |
| `PLATFORM_GW_BIZ_MSG_MAX_BYTES` | 500 | Header 描述字节上限临时假设 |
| `PLATFORM_GW_HEADER_MSG_MODE` | `ascii_fallback` | 或实验性 `utf8_raw` |
| `PLATFORM_GW_PROVIDER_API_KEY` | 空 | 非空则强制 `X-Provider-Api-Key` |

**回滚：**

1. 设 `PLATFORM_GW_ENABLED=false` 并重启；或  
2. 回退本改造提交；`/api/v1` 未改行为，旧调用方不受影响。

**应用无法补头的边界：** 进程崩溃、反向代理/容器 502/504、平台侧拒绝等，不经过本应用中间件。

---

## 11. 代码与测试

### 修改/新增文件

| 文件 | 说明 |
|---|---|
| `config/platform_gw_config.py` | 配置 |
| `src/platform_gw/*` | 常量、映射、编码、范围、适配、中间件、路由 |
| `src/main.py` | 注册中间件与平台路由 |
| `tests/api/test_platform_gw.py` | 验收测试 |
| `docs/api/北交所API统一管控平台接入说明.md` | 本文档 |

### 测试结果（本地）

```text
pytest tests/api/test_platform_gw.py -v --no-cov
14 passed
```

覆盖：成功 PS-001、HTTP200 业务失败、PV、PA、PI、未知失败、Header 清洗/长度、超限 PI-001、原 HTTP 状态、未纳入路径不受影响、不伪造平台三头。

**未执行：** 真实平台联调、生产写入、邮件发布流程。

---

## 12. 尚需平台确认的问题

1. 提供方非 200 时，平台是否透传 status / Body / `x-gw-biz-*`。  
2. 中文业务描述 Header 编码约定。  
3. 10M 口径（压缩前后、10MB vs 10MiB）。  
4. multipart 上传是否允许经平台发布，或改 MFT。  
5. 系统编码、组织编码、服务序号、一级/二级分类编码分配。  
6. 平台出口 IP 与提供方访问控制衔接方式。  
7. 是否要求提供方校验平台请求头（当前明确不赋权）。  
8. 业务失败是否必须改为 HTTP 200（当前保持原状态码）。  
9. 多主版本并存与旧 `/api/v1` 下线时间表。  
10. 候选接口（规则只读等）是否纳入下一批评审。

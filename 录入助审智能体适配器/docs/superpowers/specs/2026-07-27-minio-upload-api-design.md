# Agent MinIO 上传 API 设计文档

**日期:** 2026-07-27  
**状态:** 已批准  
**目标:** 新增 `POST /api/v1/file/minio/upload`，接收对方推送的文件字节流写入 Agent 自己的 MinIO，且不影响现有业务链路

---

## 1. 背景与约束

对方 Java 后端已有 `POST /file/minio/upload`（multipart 上传）。双写场景下，对方会把**同一份文件流**再推一份到 Agent，后续 Agent 业务接口使用本接口返回的 `file_url`。

**硬约束：**

1. Agent **绝不访问**对方 MinIO；只收 multipart 文件字节
2. **只增不改**：不改动 quality / classify / extract / audit / preview 主流程
3. 提前开发阶段的联调/自测 **不得影响现网业务**（路径隔离、不改共享配置/桶名）

**参考草案：** 仓库根目录 `Minio上传api.md`

---

## 2. 已确认决策

| 项 | 决定 |
|----|------|
| 实现路径 | 方案 1：独立新路由 + 复用现有 `MinIOClient` |
| `file_url` 前缀 | `/aiFileApi/{bucket}/{object_key}`（兼容现有 `normalize_file_url`） |
| 扩展名白名单 | pdf, doc, docx, xls, xlsx, xlsm, csv, jpg, jpeg, png, bmp, tiff, webp |
| 大小上限 | 200MB |
| `request_id` | 仅回显或自动生成；不做幂等存储 |
| 对象路径 | `yyyy/MM/dd/{uuid}.{ext}`（显式传入，不走默认 `highlights/` 前缀） |

---

## 3. 接口契约

### 3.1 基本信息

| 项目 | 说明 |
|------|------|
| 地址 | `POST /api/v1/file/minio/upload` |
| 网关映射（可选，运维侧） | `POST /otherApi/file/minio/upload` |
| Content-Type | `multipart/form-data` |
| 调用方 | 对方 Java 后端（双写时） |

### 3.2 入参

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | 上传文件二进制流 |
| file_type | String | 否 | 业务类型，仅日志，不参与对象路径 |
| request_id | String | 否 | 有则回显，无则自动生成 |

### 3.3 成功响应

统一包装：`code` / `message` / `trace_id` / `timestamp` / `data`

`data` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| url | String | Agent MinIO 完整访问地址（`get_public_url`） |
| file_name | String | 原始文件名 |
| file_url | String | `/aiFileApi/{bucket}/{object_key}`，后续业务必用 |
| object_key | String | `yyyy/MM/dd/{uuid}.{ext}` |
| file_size | Long | 字节数 |
| content_type | String | MIME |
| file_content_hash | String | MD5 |
| request_id | String | 入参回显或自动生成 |

### 3.4 错误码

| error_code | HTTP/业务码 | 含义 |
|------------|-------------|------|
| FILE_001 | 400 | 文件为空 |
| FILE_002 | 400 | 文件过大（>200MB） |
| FILE_003 | 400 | 不支持的扩展名 |
| FILE_005 | 500 | 写入 Agent MinIO 失败 |

错误体使用现有 `error_response` 格式（含 `error.error_code` / `error_message` / `details`）。

---

## 4. 处理流程

```
multipart 请求
  → 校验 file 存在且非空（FILE_001）
  → 解析扩展名，白名单校验（FILE_003）
  → 读取 bytes，校验 size ≤ 200MB（FILE_002）
  → object_key = yyyy/MM/dd/{uuid}.{ext}
  → minio_client.upload_bytes(data, object_name=object_key, content_type=...)
  → 组装 url / file_url / hash / request_id
  → success_response(data=...)
```

失败写入 MinIO 时捕获 `MinIOClientError` → `FILE_005`。

---

## 5. 隔离与不影响现网的保证

| 措施 | 说明 |
|------|------|
| 只增不改 | 新增 endpoint + 在 `api/v1/__init__.py` 追加注册 |
| 路径隔离 | 对象写在 `yyyy/MM/dd/...`，与现有溯源图 `highlights/` 分离 |
| 不改客户端默认行为 | 其他调用仍走原 `upload_bytes` 默认命名逻辑 |
| 不改 URL 规范化 | `normalize_file_url` 已支持 `/aiFileApi/`，无需修改 |
| 不访问对方 MinIO | 仅接收对方推送的文件流 |
| 测试约束 | 自测用小文件；不改 MinIO 配置/桶名；不压测共享桶到影响现网 |

---

## 6. 文件改动清单

| 文件 | 动作 | 说明 |
|------|------|------|
| `src/api/v1/endpoints/minio_upload.py` | 新增 | 路由、校验、上传、响应 |
| `src/schemas/minio_upload.py` | 新增 | 响应 data 模型 |
| `src/api/v1/__init__.py` | 仅追加 | `include_router(minio_upload_router)` |
| 现有业务文件 | 不改 | file / classification / extraction / audit / preview / minio client 默认逻辑 / normalize_file_url |

**复用：**

- `src.utils.minio.client.get_minio_client`
- `src.schemas.base.success_response` / `error_response`

---

## 7. FastAPI 签名（实现参考）

```python
@router.post("/minio/upload")
async def minio_upload(
    file: UploadFile = File(...),
    file_type: Optional[str] = Form(None),
    request_id: Optional[str] = Form(None),
):
    ...
```

Router：`APIRouter(prefix="/file", tags=["文件上传"])`，挂载后完整路径为 `/api/v1/file/minio/upload`。

---

## 8. 验收标准

1. `POST /api/v1/file/minio/upload` 可上传白名单内文件并返回完整 `data` 字段
2. 空文件 / 超大 / 非法扩展名分别返回 FILE_001 / FILE_002 / FILE_003
3. MinIO 写入失败返回 FILE_005
4. 返回的 `file_url` 可被现有 `normalize_file_url` 转为 Agent MinIO 完整 URL
5. 未修改任何现有业务 endpoint 行为；对象不写入 `highlights/` 前缀
6. 自测不改动 MinIO 配置与桶名

---

## 9. 非目标（本次不做）

- 批量 `files[]` 上传
- `request_id` 真幂等（缓存/DB）
- `/agentFileApi` 新前缀及网关改造
- 从对方 MinIO URL 拉取文件
- 溯源图上传（仍走现有 highlight 流程）

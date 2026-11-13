# Agent MinIO 上传 API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `POST /api/v1/file/minio/upload`，接收 multipart 文件流写入 Agent MinIO，返回后续业务可用的 `file_url`，且不影响现有业务。

**Architecture:** 独立 endpoint（`minio_upload.py`）+ schema；复用 `get_minio_client().upload_bytes`（显式 `object_name`，路径 `yyyy/MM/dd/{uuid}.{ext}`，避开 `highlights/`）；统一 `success_response` / `error_response`；`file_url` 使用 `/aiFileApi/{bucket}/{object_key}`。

**Tech Stack:** FastAPI, UploadFile/File/Form, 现有 MinIOClient, Pydantic schemas, pytest + TestClient（Mock MinIO，禁止真写共享桶）

**Spec:** `docs/superpowers/specs/2026-07-27-minio-upload-api-design.md`

## Global Constraints

- 只增不改：不修改 quality/classify/extract/audit/preview 主逻辑，不改 `normalize_file_url`，不改 MinIO 默认命名
- Agent 不访问对方 MinIO，只收文件字节流
- 扩展名白名单：pdf/doc/docx/xls/xlsx/xlsm/csv/jpg/jpeg/png/bmp/tiff/webp
- 大小上限：200MB
- `request_id`：回显或自动生成，无幂等存储
- `file_url`：`/aiFileApi/{bucket}/{object_key}`
- 自测/单测必须 Mock MinIO，不得向共享桶写大文件影响现网
- **所有 git commit message 使用中文**

---

## File Structure

| 文件 | 职责 |
|------|------|
| `src/schemas/minio_upload.py` | 响应 data 模型 `MinioUploadData` |
| `src/api/v1/endpoints/minio_upload.py` | 校验 + 上传 + 响应 |
| `src/api/v1/__init__.py` | 追加 `include_router` |
| `tests/api/test_minio_upload.py` | Mock MinIO 的接口单测 |

---

### Task 1: Schema + 上传端点 + 路由注册

**Files:**
- Create: `src/schemas/minio_upload.py`
- Create: `src/api/v1/endpoints/minio_upload.py`
- Modify: `src/api/v1/__init__.py`
- Test: `tests/api/test_minio_upload.py`

**Interfaces:**
- Consumes: `get_minio_client()`, `MinIOClient.upload_bytes`, `MinIOClient.get_public_url`, `MinIOClient.bucket_name`, `MinIOClientError`, `success_response`, `error_response`
- Produces: `POST /api/v1/file/minio/upload`；`MinioUploadData` 字段见下方实现

- [ ] **Step 1: 创建 schema**

创建 `src/schemas/minio_upload.py`：

```python
"""MinIO 上传接口响应模型"""

from typing import Optional
from pydantic import BaseModel, Field


class MinioUploadData(BaseModel):
    """MinIO 上传成功 data"""
    url: str = Field(..., description="Agent MinIO 完整访问地址")
    file_name: str = Field(..., description="原始文件名")
    file_url: str = Field(..., description="后续业务使用的相对路径 /aiFileApi/{bucket}/{object_key}")
    object_key: str = Field(..., description="对象路径 yyyy/MM/dd/{uuid}.{ext}")
    file_size: int = Field(..., description="文件字节数")
    content_type: str = Field(..., description="MIME 类型")
    file_content_hash: str = Field(..., description="MD5 哈希")
    request_id: str = Field(..., description="请求 ID（回显或自动生成）")
```

- [ ] **Step 2: 创建上传端点**

创建 `src/api/v1/endpoints/minio_upload.py`：

```python
"""
Agent MinIO 文件上传接口

对方将文件字节流推送到本接口，写入 Agent 自己的 MinIO。
不访问对方 MinIO；不影响现有 highlights 溯源路径。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger

from src.schemas.base import error_response, success_response
from src.schemas.minio_upload import MinioUploadData
from src.utils.minio.client import MinIOClientError, get_minio_client

router = APIRouter(prefix="/file", tags=["文件上传"])

ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "xlsm", "csv",
    "jpg", "jpeg", "png", "bmp", "tiff", "webp",
}
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB


def _extract_extension(filename: Optional[str]) -> Optional[str]:
    if not filename or "." not in filename:
        return None
    return filename.rsplit(".", 1)[-1].lower()


@router.post(
    "/minio/upload",
    summary="上传文件到 Agent MinIO",
    description="接收 multipart 文件流，写入 Agent MinIO，返回 url / file_url 等字段。",
)
async def minio_upload(
    file: UploadFile = File(...),
    file_type: Optional[str] = Form(None),
    request_id: Optional[str] = Form(None),
):
    trace_id = f"trace_{uuid.uuid4().hex[:16]}"
    resolved_request_id = request_id or f"req_{uuid.uuid4().hex[:16]}"

    original_name = file.filename or ""
    if not original_name.strip():
        return JSONResponse(
            status_code=400,
            content=error_response(
                error_code="FILE_001",
                error_message="文件不能为空",
                message="Bad Request",
                code=400,
                details=[{"field": "file", "message": "请上传文件"}],
                trace_id=trace_id,
            ),
        )

    ext = _extract_extension(original_name)
    if not ext or ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content=error_response(
                error_code="FILE_003",
                error_message="不支持的扩展名",
                message="Bad Request",
                code=400,
                details=[{"field": "file", "message": f"不支持的扩展名: {ext or '(无)'}"}],
                trace_id=trace_id,
            ),
        )

    file_bytes = await file.read()
    if not file_bytes:
        return JSONResponse(
            status_code=400,
            content=error_response(
                error_code="FILE_001",
                error_message="文件不能为空",
                message="Bad Request",
                code=400,
                details=[{"field": "file", "message": "请上传文件"}],
                trace_id=trace_id,
            ),
        )

    if len(file_bytes) > MAX_FILE_SIZE:
        return JSONResponse(
            status_code=400,
            content=error_response(
                error_code="FILE_002",
                error_message="文件过大",
                message="Bad Request",
                code=400,
                details=[{
                    "field": "file",
                    "message": f"文件大小超过上限 200MB，当前 {len(file_bytes)} 字节",
                }],
                trace_id=trace_id,
            ),
        )

    content_type = file.content_type or "application/octet-stream"
    object_key = f"{datetime.now().strftime('%Y/%m/%d')}/{uuid.uuid4().hex}.{ext}"
    file_hash = hashlib.md5(file_bytes).hexdigest()

    logger.info(
        f"[{trace_id}] MinIO 上传开始 | file={original_name} | "
        f"size={len(file_bytes)} | file_type={file_type} | request_id={resolved_request_id}"
    )

    try:
        minio_client = get_minio_client()
        minio_client.upload_bytes(
            data=file_bytes,
            object_name=object_key,
            content_type=content_type,
        )
        public_url = minio_client.get_public_url(object_key)
        bucket = minio_client.bucket_name
    except MinIOClientError as e:
        logger.error(f"[{trace_id}] MinIO 写入失败: {e}")
        return JSONResponse(
            status_code=500,
            content=error_response(
                error_code="FILE_005",
                error_message="写入 Agent MinIO 失败",
                message="Internal Server Error",
                code=500,
                details=[{"field": "file", "message": str(e)}],
                trace_id=trace_id,
            ),
        )
    except Exception as e:
        logger.error(f"[{trace_id}] MinIO 上传异常: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=error_response(
                error_code="FILE_005",
                error_message="写入 Agent MinIO 失败",
                message="Internal Server Error",
                code=500,
                details=[{"field": "file", "message": str(e)}],
                trace_id=trace_id,
            ),
        )

    data = MinioUploadData(
        url=public_url,
        file_name=original_name,
        file_url=f"/aiFileApi/{bucket}/{object_key}",
        object_key=object_key,
        file_size=len(file_bytes),
        content_type=content_type,
        file_content_hash=file_hash,
        request_id=resolved_request_id,
    )

    logger.info(
        f"[{trace_id}] MinIO 上传成功 | object_key={object_key} | file_url={data.file_url}"
    )

    return success_response(data=data.model_dump(), trace_id=trace_id)
```

- [ ] **Step 3: 注册路由**

修改 `src/api/v1/__init__.py`：在现有 import 后追加：

```python
from src.api.v1.endpoints.minio_upload import router as minio_upload_router
```

在 `include_router` 区域追加（放在 `file_router` 附近即可）：

```python
api_router.include_router(minio_upload_router)
```

**注意：** 只追加，不改动其他 router 注册顺序含义以外的逻辑。

- [ ] **Step 4: 编写 Mock MinIO 单测（禁止真写桶）**

创建 `tests/api/test_minio_upload.py`：

```python
"""MinIO 上传接口单测（Mock MinIO，不写真实桶）"""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.v1.endpoints.minio_upload import router
from src.utils.minio.client import MinIOClientError


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _mock_minio():
    mock = MagicMock()
    mock.bucket_name = "bjs-file"
    mock.upload_bytes.return_value = "/otherApi/preview/files/2026/07/27/abc.pdf"
    mock.get_public_url.side_effect = (
        lambda key: f"http://10.254.89.130:9000/bjs-file/{key}"
    )
    return mock


def test_upload_success(client):
    mock = _mock_minio()
    with patch(
        "src.api.v1.endpoints.minio_upload.get_minio_client",
        return_value=mock,
    ):
        resp = client.post(
            "/api/v1/file/minio/upload",
            files={"file": ("申请书.pdf", BytesIO(b"%PDF-1.4 test"), "application/pdf")},
            data={"file_type": "info_disclosure_application", "request_id": "req_test_001"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["file_name"] == "申请书.pdf"
    assert body["data"]["request_id"] == "req_test_001"
    assert body["data"]["file_url"].startswith("/aiFileApi/bjs-file/")
    assert body["data"]["object_key"].endswith(".pdf")
    assert "highlights/" not in body["data"]["object_key"]
    mock.upload_bytes.assert_called_once()
    kwargs = mock.upload_bytes.call_args.kwargs
    assert kwargs["object_name"] == body["data"]["object_key"]


def test_upload_empty_file(client):
    with patch(
        "src.api.v1.endpoints.minio_upload.get_minio_client",
        return_value=_mock_minio(),
    ):
        resp = client.post(
            "/api/v1/file/minio/upload",
            files={"file": ("empty.pdf", BytesIO(b""), "application/pdf")},
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["error_code"] == "FILE_001"


def test_upload_bad_extension(client):
    with patch(
        "src.api.v1.endpoints.minio_upload.get_minio_client",
        return_value=_mock_minio(),
    ):
        resp = client.post(
            "/api/v1/file/minio/upload",
            files={"file": ("virus.exe", BytesIO(b"MZ"), "application/octet-stream")},
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["error_code"] == "FILE_003"


def test_upload_minio_failure(client):
    mock = _mock_minio()
    mock.upload_bytes.side_effect = MinIOClientError("put failed")
    with patch(
        "src.api.v1.endpoints.minio_upload.get_minio_client",
        return_value=mock,
    ):
        resp = client.post(
            "/api/v1/file/minio/upload",
            files={"file": ("申请书.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
    assert resp.status_code == 500
    assert resp.json()["error"]["error_code"] == "FILE_005"
```

如项目无 `tests/__init__.py` / `tests/api/__init__.py`，一并创建空文件。

- [ ] **Step 5: 运行单测**

```bash
pytest tests/api/test_minio_upload.py -v
```

Expected: 全部 PASS（若缺 pytest/httpx，先 `pip install pytest httpx`）

- [ ] **Step 6: 自检不动现网**

确认 git diff **不包含** 以下文件的业务逻辑改动：

- `src/api/v1/endpoints/file.py`
- `src/api/v1/endpoints/classification.py`
- `src/api/v1/endpoints/extraction.py`
- `src/api/v1/endpoints/audit.py`
- `src/api/v1/endpoints/preview.py`
- `src/utils/file_handler.py`（normalize_file_url）
- `config/minio_config.py`

仅允许新增文件 + `__init__.py` 追加 import/include_router。

- [ ] **Step 7: 中文 commit**

```bash
git add src/schemas/minio_upload.py src/api/v1/endpoints/minio_upload.py src/api/v1/__init__.py tests/api/test_minio_upload.py tests/__init__.py tests/api/__init__.py docs/superpowers/specs/2026-07-27-minio-upload-api-design.md docs/superpowers/plans/2026-07-27-minio-upload-api.md
git commit -m "$(cat <<'EOF'
新增 Agent MinIO 文件上传接口，支持对方双写推送且不影响现有业务

EOF
)"
```

Windows PowerShell 可用：

```powershell
git add src/schemas/minio_upload.py src/api/v1/endpoints/minio_upload.py src/api/v1/__init__.py tests/api/test_minio_upload.py tests/__init__.py tests/api/__init__.py docs/superpowers/specs/2026-07-27-minio-upload-api-design.md docs/superpowers/plans/2026-07-27-minio-upload-api.md
git commit -m "新增 Agent MinIO 文件上传接口，支持对方双写推送且不影响现有业务"
```

---

## Spec Coverage Checklist

| Spec 要求 | Task |
|-----------|------|
| POST /api/v1/file/minio/upload | Task 1 |
| multipart file + 可选 file_type/request_id | Task 1 |
| 白名单扩展名 / 200MB / 空文件 | Task 1 + 单测 |
| object_key = yyyy/MM/dd/uuid.ext | Task 1 |
| url / file_name / file_url / object_key / size / content_type / hash / request_id | Task 1 |
| FILE_001/002/003/005 | Task 1 + 单测 |
| 不改现有业务、路径避开 highlights | Task 1 Step 6 |
| Mock 测试不影响共享桶 | Task 1 单测 |

## Non-goals（本计划不做）

- 批量 files[]、真幂等、agentFileApi 前缀、对方 MinIO 拉取、真实联调写桶

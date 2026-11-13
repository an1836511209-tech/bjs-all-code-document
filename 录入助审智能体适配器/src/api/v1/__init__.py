"""
API v1 路由聚合模块
"""

from fastapi import APIRouter

from src.api.v1.endpoints.file import router as file_router
from src.api.v1.endpoints.minio_upload import router as minio_upload_router
from src.api.v1.endpoints.rule_config import router as rule_config_router
from src.api.v1.endpoints.rule_config_web import router as rule_config_web_router
from src.api.v1.endpoints.extraction import router as extraction_router
from src.api.v1.endpoints.audit import router as audit_router
from src.api.v1.endpoints.task import router as task_router
from src.api.v1.endpoints.preview import router as preview_router
from src.api.v1.endpoints.classification import router as classification_router


# 创建v1 API路由器
api_router = APIRouter(prefix="/api/v1")

# 注册各个端点路由
api_router.include_router(file_router)
api_router.include_router(minio_upload_router)
api_router.include_router(rule_config_router)
api_router.include_router(extraction_router)
api_router.include_router(audit_router)
api_router.include_router(task_router)
api_router.include_router(preview_router)
api_router.include_router(classification_router)

# 导出路由器
__all__ = ["api_router"]

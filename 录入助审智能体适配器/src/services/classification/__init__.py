"""
文件分类服务模块
"""

from src.services.classification.service import (
    FileClassificationAPIService,
    get_classification_api_service
)

__all__ = [
    "FileClassificationAPIService",
    "get_classification_api_service"
]

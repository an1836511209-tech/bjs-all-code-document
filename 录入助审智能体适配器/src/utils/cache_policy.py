"""
提取结果缓存策略

判定提取结果是否可写入/复用 files_hash 缓存索引。
规则：success + pending > failed（严格大于）时可缓存。
"""

from typing import Any, Dict, List, Optional

from src.schemas.extraction import FieldExtractionStatus


def _safe_get(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_countable_failed(error_message: Optional[str]) -> bool:
    """与 ExtractionService._calculate_field_statistics 保持一致的可计数失败判定。"""
    msg = error_message or ""
    if msg == "未找到提取结果":
        return False
    if msg.startswith("级联未触发"):
        return False
    if "未找到参考材料对应的文件" in msg:
        return False
    if "级联首字段" in msg and "依赖的文件不存在" in msg:
        return False
    return True


def calculate_field_statistics(results: List) -> Dict[str, int]:
    """
    从 results 列表计算字段统计信息（与 ExtractionService 逻辑一致）。

    Returns:
        success_count, pending_count, failed_count, total_fields
    """
    if not results:
        return {
            "success_count": 0,
            "pending_count": 0,
            "failed_count": 0,
            "total_fields": 0,
        }

    success_count = sum(
        1
        for r in results
        if _safe_get(r, "field_status") == FieldExtractionStatus.SUCCESS
    )
    pending_count = sum(
        1
        for r in results
        if _safe_get(r, "field_status") == FieldExtractionStatus.PENDING
    )
    failed_count = sum(
        1
        for r in results
        if _safe_get(r, "field_status") == FieldExtractionStatus.FAILED
        and _is_countable_failed(_safe_get(r, "error_message"))
    )
    total_fields = success_count + pending_count + failed_count

    return {
        "success_count": success_count,
        "pending_count": pending_count,
        "failed_count": failed_count,
        "total_fields": total_fields,
    }


def is_cacheable_extraction_result(result: Any) -> bool:
    """
    判断提取结果是否满足 files_hash 缓存条件。

    规则：(success_count + pending_count) > failed_count
    """
    if not isinstance(result, dict):
        return False

    results = result.get("results")
    if not isinstance(results, list) or not results:
        return False

    stats = calculate_field_statistics(results)
    good_count = stats["success_count"] + stats["pending_count"]
    return good_count > stats["failed_count"]

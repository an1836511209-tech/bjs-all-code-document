"""
JSON 安全序列化工具

将 Python 对象递归转换为 json.dumps 可接受的结构，
供任务存储等需要持久化 JSON 的场景使用。
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from typing import Any, Optional, Set

# 任务持久化时排除的二进制或大字段
_SKIP_BINARY_KEYS = frozenset({
    "pdf_content",
    "file_content",
    "corrected_file_content",
})


class TaskSerializationError(TypeError):
    """任务数据无法安全序列化为 JSON"""


def to_json_safe(obj: Any, *, _seen: Optional[Set[int]] = None) -> Any:
    """
    递归将对象转换为 JSON 可序列化结构。

    处理策略：
    - 基础类型：原样返回
    - bytes：丢弃（返回 None，字典键则跳过）
    - datetime/date：isoformat 字符串
    - Enum：value
    - Decimal：str
    - list/tuple/set：递归转换列表
    - dict：递归转换，跳过二进制字段
    - Pydantic model：model_dump(mode='json')
    - dataclass：asdict 后递归
    - 带 __dict__ 的对象（含 SimpleNamespace）：属性转 dict 后递归
    - 其他：str(obj)
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, bytes):
        return None

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    if isinstance(obj, Enum):
        return obj.value

    if isinstance(obj, Decimal):
        return str(obj)

    if isinstance(obj, (list, tuple, set)):
        return [to_json_safe(item, _seen=_seen) for item in obj]

    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key in _SKIP_BINARY_KEYS or isinstance(value, bytes):
                continue
            result[key] = to_json_safe(value, _seen=_seen)
        return result

    if _seen is None:
        _seen = set()

    obj_id = id(obj)
    if obj_id in _seen:
        return str(obj)
    _seen.add(obj_id)

    try:
        if hasattr(obj, "model_dump"):
            try:
                dumped = obj.model_dump(mode="json")
            except Exception:
                dumped = obj.model_dump()
            return to_json_safe(dumped, _seen=_seen)

        if is_dataclass(obj) and not isinstance(obj, type):
            return to_json_safe(asdict(obj), _seen=_seen)

        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            try:
                return to_json_safe(obj.to_dict(), _seen=_seen)
            except Exception:
                pass

        if isinstance(obj, SimpleNamespace) or (
            hasattr(obj, "__dict__") and not isinstance(obj, type)
        ):
            data = {
                key: value
                for key, value in vars(obj).items()
                if not key.startswith("_") and key not in _SKIP_BINARY_KEYS
            }
            return to_json_safe(data, _seen=_seen)
    finally:
        _seen.discard(obj_id)

    return str(obj)


def precheck_json_serializable(value: Any, *, field_name: str = "value") -> Any:
    """
    写入前预检：转换为 JSON 安全结构并验证 json.dumps 可通过。

    Args:
        value: 待持久化的 Python 对象
        field_name: 字段名（用于错误信息）

    Returns:
        可安全 json.dumps 的对象

    Raises:
        TaskSerializationError: 预检后仍无法序列化
    """
    sanitized = to_json_safe(value)
    try:
        json.dumps(sanitized, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise TaskSerializationError(
            f"任务字段 {field_name!r} 无法序列化为 JSON: {exc}"
        ) from exc
    return sanitized


def safe_json_dumps(value: Any, *, field_name: str = "value", **kwargs) -> str:
    """
    预检并序列化为 JSON 字符串。

    Args:
        value: 待序列化对象；None 或空 dict 等 falsy 值按调用方约定处理
        field_name: 字段名（用于错误信息）
        **kwargs: 传给 json.dumps 的参数
    """
    if value is None:
        return ""
    sanitized = precheck_json_serializable(value, field_name=field_name)
    if kwargs:
        return json.dumps(sanitized, **kwargs)
    return json.dumps(sanitized, ensure_ascii=False)

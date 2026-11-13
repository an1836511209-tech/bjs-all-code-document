"""平台适配范围匹配"""

from __future__ import annotations

import re
from typing import Iterable, Pattern

from config.platform_gw_config import PLATFORM_GW_INCLUDED_PATHS, PLATFORM_GW_PREFIX


def _template_to_regex(template: str) -> Pattern[str]:
    """
    将含 {param} 的路径模板转为正则（当前白名单均为静态路径，仍保留模板能力）。
    """
    parts = []
    for segment in template.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            parts.append(r"[^/]+")
        else:
            parts.append(re.escape(segment))
    return re.compile("^/" + "/".join(parts) + "$")


_COMPILED = [_template_to_regex(p) for p in sorted(PLATFORM_GW_INCLUDED_PATHS)]


def normalize_relative_path(path: str, prefix: str | None = None) -> str:
    base = (prefix or PLATFORM_GW_PREFIX).rstrip("/")
    raw = path.split("?", 1)[0]
    if raw.startswith(base):
        rel = raw[len(base) :] or "/"
    else:
        rel = raw
    if not rel.startswith("/"):
        rel = "/" + rel
    # 去掉末尾多余斜杠（根除外）
    if len(rel) > 1 and rel.endswith("/"):
        rel = rel.rstrip("/")
    return rel


def is_platform_prefix(path: str, prefix: str | None = None) -> bool:
    base = (prefix or PLATFORM_GW_PREFIX).rstrip("/")
    raw = path.split("?", 1)[0]
    return raw == base or raw.startswith(base + "/")


def is_included_path(path: str, prefix: str | None = None) -> bool:
    if not is_platform_prefix(path, prefix):
        return False
    rel = normalize_relative_path(path, prefix)
    return any(p.match(rel) for p in _COMPILED)


def is_special_non_json_response(content_type: str | None) -> bool:
    if not content_type:
        return False
    ct = content_type.lower()
    if "application/json" in ct:
        return False
    # 流式 / 文件 / SSE / 二进制等不套用 JSON 大小替换
    markers = (
        "text/event-stream",
        "application/octet-stream",
        "multipart/",
        "image/",
        "audio/",
        "video/",
        "application/pdf",
        "application/zip",
    )
    return any(m in ct for m in markers)

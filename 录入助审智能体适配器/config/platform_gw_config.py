"""
北交所 API 统一管控平台 — 服务提供方适配配置

说明：
- 报文 10M 阈值的字节口径、压缩前后计算方式尚未由平台书面确认，此处为可配置临时假设。
- 中文业务描述写入 HTTP Header 的线上编码方式尚未确认，默认 ascii_fallback。
"""

from __future__ import annotations

import os
from typing import FrozenSet


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# 是否启用平台接入路由与中间件（关闭后 /api/platform 不注册业务头逻辑仍可保留模块）
PLATFORM_GW_ENABLED: bool = _env_bool("PLATFORM_GW_ENABLED", True)

# 平台接入路径前缀（项目设计选择，非平台强制）
PLATFORM_GW_PREFIX: str = os.getenv("PLATFORM_GW_PREFIX", "/api/platform/v1").rstrip("/") or "/api/platform/v1"

# 报文大小阈值（字节）。临时假设：按最终序列化 UTF-8 字节、未压缩体积计算。
PLATFORM_GW_MAX_PAYLOAD_BYTES: int = int(
    os.getenv("PLATFORM_GW_MAX_PAYLOAD_BYTES", str(10 * 1024 * 1024))
)

# x-gw-biz-msg 最大长度口径：临时按 UTF-8 字节计（VARCHAR2(500) 在不同字符集下语义待确认）
PLATFORM_GW_BIZ_MSG_MAX_BYTES: int = int(os.getenv("PLATFORM_GW_BIZ_MSG_MAX_BYTES", "500"))

# Header 中文描述模式：
# - ascii_fallback: 对外 Header 使用 ASCII 安全描述（可运行）；完整中文在 Body/日志
# - utf8_raw: 实验性直接写入 UTF-8 中文（联调确认前不要当作平台规范）
PLATFORM_GW_HEADER_MSG_MODE: str = os.getenv("PLATFORM_GW_HEADER_MSG_MODE", "ascii_fallback").strip().lower()

# 可选：提供方侧访问密钥。配置后平台入口要求 X-Provider-Api-Key 匹配；
# 不信任 x-gw-appid/x-gw-org。未配置则不额外鉴权（与现网 /api/v1 一致）。
PLATFORM_GW_PROVIDER_API_KEY: str = os.getenv("PLATFORM_GW_PROVIDER_API_KEY", "").strip()

# 显式纳入平台适配的相对路径（相对 PLATFORM_GW_PREFIX）
# 未列出的路径即使误挂载也不会补业务头 / 做大小替换
PLATFORM_GW_INCLUDED_PATHS: FrozenSet[str] = frozenset(
    {
        "/file/quality-check",
        "/file/classification",
        "/file/minio/upload",
        "/extraction/sync",
        "/audit/sync",
        "/task",
        "/task/cancel",
    }
)

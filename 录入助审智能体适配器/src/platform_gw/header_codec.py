"""
业务响应头编码与安全处理

中文 Header 编码方式平台未书面确认：默认 ascii_fallback，不得宣称已符合中文描述要求。
"""

from __future__ import annotations

from typing import Tuple

from config.platform_gw_config import (
    PLATFORM_GW_BIZ_MSG_MAX_BYTES,
    PLATFORM_GW_HEADER_MSG_MODE,
)


def sanitize_header_value(value: str) -> str:
    """去除 CR/LF 等非法头字符，防止响应头注入。"""
    if value is None:
        return ""
    text = str(value)
    for ch in ("\r", "\n", "\0"):
        text = text.replace(ch, " ")
    # 折叠异常空白
    return " ".join(text.split())


def _truncate_utf8_bytes(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    truncated = raw[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8") + "..."
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return "..."


def encode_biz_msg(ascii_msg: str, zh_msg: str) -> Tuple[str, str]:
    """
    返回 (header_value, mode_used)

    ascii_fallback: Header 仅 ASCII；中文完整描述应依赖 Body / 内部日志。
    utf8_raw: 实验性直接写入中文（联调确认前勿当作规范）。
    """
    mode = PLATFORM_GW_HEADER_MSG_MODE
    if mode == "utf8_raw":
        value = sanitize_header_value(zh_msg or ascii_msg)
        value = _truncate_utf8_bytes(value, PLATFORM_GW_BIZ_MSG_MAX_BYTES)
        return value, mode

    # 默认 ascii_fallback
    value = sanitize_header_value(ascii_msg or "Business message pending encoding confirmation")
    # 强制剥离非 ASCII
    value = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in value)
    value = _truncate_utf8_bytes(value, PLATFORM_GW_BIZ_MSG_MAX_BYTES)
    return value, "ascii_fallback"


def validate_encoded_length(value: str, max_bytes: int | None = None) -> bool:
    limit = max_bytes if max_bytes is not None else PLATFORM_GW_BIZ_MSG_MAX_BYTES
    return len(value.encode("utf-8")) <= limit

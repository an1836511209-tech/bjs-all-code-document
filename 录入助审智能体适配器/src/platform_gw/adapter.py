"""响应适配：设置提供方业务头、报文超限处理"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

from loguru import logger

from config.platform_gw_config import PLATFORM_GW_MAX_PAYLOAD_BYTES
from src.platform_gw.constants import (
    BIZ_CODE_PAYLOAD_TOO_LARGE,
    BIZ_CODE_SUCCESS,
    BIZ_MSG_PAYLOAD_TOO_LARGE_ASCII,
    BIZ_MSG_PAYLOAD_TOO_LARGE_ZH,
    HEADER_GW_BIZ_CODE,
    HEADER_GW_BIZ_MSG,
    PLATFORM_GENERATED_HEADERS,
)
from src.platform_gw.header_codec import encode_biz_msg
from src.platform_gw.mapping import BUSINESS_CODE_MAP, resolve_from_response_body


def _parse_json_bytes(body: bytes) -> Optional[Dict[str, Any]]:
    if not body:
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def apply_biz_headers(
    headers: MutableMapping[str, str],
    biz_code: str,
    ascii_msg: str,
    zh_msg: str,
    *,
    overwrite_success_only: bool = True,
) -> None:
    """
    写入提供方业务头。永不写入平台生成的三个头。

    overwrite_success_only:
      若已存在失败业务码，成功路径不得覆盖。
    """
    existing = headers.get(HEADER_GW_BIZ_CODE) or headers.get(HEADER_GW_BIZ_CODE.title())
    if existing:
        # 归一化查找
        for k, v in list(headers.items()):
            if k.lower() == HEADER_GW_BIZ_CODE:
                existing = v
                break

    if existing and overwrite_success_only:
        if existing != BIZ_CODE_SUCCESS and biz_code == BIZ_CODE_SUCCESS:
            return
        # 已有明确失败码时，不应用成功
        if existing.startswith(("PV-", "PA-", "PI-", "PO-")) and biz_code == BIZ_CODE_SUCCESS:
            return

    header_msg, mode = encode_biz_msg(ascii_msg, zh_msg)
    headers[HEADER_GW_BIZ_CODE] = biz_code
    headers[HEADER_GW_BIZ_MSG] = header_msg
    # 清理可能被误设的平台头（提供方不得伪造）
    for name in list(headers.keys()):
        if name.lower() in {h.lower() for h in PLATFORM_GENERATED_HEADERS}:
            logger.warning(f"移除提供方侧不应出现的平台响应头: {name}")
            del headers[name]

    logger.debug(
        f"platform_gw biz headers set: code={biz_code}, msg_mode={mode}, msg={header_msg!r}"
    )


def build_payload_too_large_body(trace_id: Optional[str] = None) -> Dict[str, Any]:
    mapping = BUSINESS_CODE_MAP["PAYLOAD_TOO_LARGE"]
    return {
        "code": 413,
        "message": "Payload Too Large",
        "trace_id": trace_id or f"trace_payload_{int(datetime.utcnow().timestamp())}",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "error": {
            "error_code": "PAYLOAD_TOO_LARGE",
            "error_message": mapping.zh_msg,
            "details": None,
        },
    }


def adapt_json_response(
    body: bytes,
    http_status: int,
    headers: MutableMapping[str, str],
    *,
    max_bytes: int | None = None,
) -> Tuple[bytes, int, Dict[str, str]]:
    """
    对 JSON 响应做业务码映射与超限检查。
    返回 (new_body, new_status, header_updates)
    """
    limit = max_bytes if max_bytes is not None else PLATFORM_GW_MAX_PAYLOAD_BYTES
    header_updates: Dict[str, str] = {}

    # 先解析业务结果（即便后续因超限替换，也要避免误报成功）
    parsed = _parse_json_bytes(body)
    biz_code, ascii_msg, zh_msg = resolve_from_response_body(parsed, http_status)

    # 超限：不得截断 JSON；整体替换为 PI-001
    if len(body) > limit:
        logger.warning(
            f"platform_gw payload exceeds limit: size={len(body)} limit={limit} "
            f"original_biz_code={biz_code}"
        )
        trace_id = None
        if isinstance(parsed, dict):
            trace_id = parsed.get("trace_id")
        new_obj = build_payload_too_large_body(trace_id=trace_id)
        new_body = json.dumps(new_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # 保持可被调用方识别；不强制改成 200。使用 413 表达体积问题，同时业务码 PI-001。
        # 若原状态非 2xx，保留原状态以免掩盖更严重错误。
        new_status = http_status if http_status >= 400 else 413
        apply_biz_headers(
            header_updates,
            BIZ_CODE_PAYLOAD_TOO_LARGE,
            BIZ_MSG_PAYLOAD_TOO_LARGE_ASCII,
            BIZ_MSG_PAYLOAD_TOO_LARGE_ZH,
            overwrite_success_only=False,
        )
        header_updates["content-length"] = str(len(new_body))
        header_updates["content-type"] = "application/json; charset=utf-8"
        return new_body, new_status, header_updates

    apply_biz_headers(header_updates, biz_code, ascii_msg, zh_msg)
    return body, http_status, header_updates


def merge_headers(target: MutableMapping[str, str], updates: Mapping[str, str]) -> None:
    # 先删同名不同大小写，再写入
    lower_map = {k.lower(): k for k in list(target.keys())}
    for key, value in updates.items():
        old = lower_map.get(key.lower())
        if old and old != key:
            del target[old]
        target[key] = value

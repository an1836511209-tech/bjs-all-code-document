"""
业务码映射表（集中维护）

说明：
- PS-001 / PI-001 等前缀类别来自平台规范 V0.5 §5.2。
- 具体子码（如 PV-001、PA-001、PI-002）为本项目约定，不能冒充平台统一定义。
- 未映射的业务失败不得默认标记为 PS-001。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class BizMapping:
    platform_code: str
    ascii_msg: str
    zh_msg: str


# 原业务码 / 异常类型 → 平台业务码
BUSINESS_CODE_MAP: Dict[str, BizMapping] = {
    # 成功
    "SUCCESS": BizMapping("PS-001", "Business processed successfully", "业务处理成功"),
    # 参数 / 校验
    "VALIDATION_ERROR": BizMapping(
        "PV-001",
        "Request parameter validation failed",
        "请求参数验证失败",
    ),
    "FILE_001": BizMapping("PV-002", "File must not be empty", "文件不能为空"),
    "FILE_002": BizMapping("PV-003", "File size exceeds limit", "文件过大"),
    "FILE_003": BizMapping("PV-004", "Unsupported file extension", "不支持的扩展名"),
    # 认证 / 权限（提供方自身）
    "AUTH_REQUIRED": BizMapping(
        "PA-001",
        "Provider authentication required",
        "提供方认证失败：缺少访问凭证",
    ),
    "AUTH_INVALID": BizMapping(
        "PA-002",
        "Provider authentication failed",
        "提供方认证失败：访问凭证无效",
    ),
    "PERMISSION_DENIED": BizMapping(
        "PA-003",
        "Provider permission denied",
        "提供方权限不足",
    ),
    # 内部异常（PI-001 专用于报文超限，勿复用）
    "INTERNAL_ERROR": BizMapping(
        "PI-002",
        "Provider internal error",
        "服务器内部错误，请稍后重试",
    ),
    "HTTP_ERROR": BizMapping(
        "PI-003",
        "Provider HTTP error",
        "提供方处理失败",
    ),
    "FILE_005": BizMapping(
        "PI-004",
        "Object storage write failed",
        "写入对象存储失败",
    ),
    "PAYLOAD_TOO_LARGE": BizMapping(
        "PI-001",
        "Query result exceeds 10M; narrow the query range and retry",
        "查询结果大于10M，请缩小查询区间或范围再执行查询",
    ),
    # 未归类
    "UNKNOWN_BUSINESS_FAILURE": BizMapping(
        "PO-001",
        "Unmapped business failure",
        "未映射的业务失败",
    ),
    "UNKNOWN_EXCEPTION": BizMapping(
        "PO-002",
        "Unclassified provider exception",
        "未归类异常",
    ),
}


def _join_details(details: Any) -> str:
    if not details or not isinstance(details, list):
        return ""
    parts = []
    for item in details:
        if not isinstance(item, dict):
            continue
        field = item.get("field") or ""
        message = item.get("message") or ""
        if field and message:
            # 尽量满足“中文名[FIELD]不能为空”形态；无中文名时用字段名
            parts.append(f"{message}[{field}]" if "[" not in str(message) else str(message))
        elif message:
            parts.append(str(message))
        elif field:
            parts.append(f"Field [{field}] is invalid")
    return "|".join(parts)


def resolve_from_error_code(
    error_code: Optional[str],
    error_message: Optional[str] = None,
    details: Any = None,
) -> Tuple[str, str, str]:
    """
    Returns: (platform_code, ascii_msg, zh_msg)
    """
    key = (error_code or "").strip() or "UNKNOWN_BUSINESS_FAILURE"
    mapping = BUSINESS_CODE_MAP.get(key)
    if mapping is None:
        mapping = BUSINESS_CODE_MAP["UNKNOWN_BUSINESS_FAILURE"]
        # 保留原业务码信息到描述，避免误报成功
        extra_zh = error_message or key
        extra_ascii = f"Unmapped business code [{key}]"
        detail_part = _join_details(details)
        zh = "|".join(p for p in [extra_zh, detail_part] if p)
        ascii_msg = "|".join(p for p in [extra_ascii, detail_part] if p) or mapping.ascii_msg
        return mapping.platform_code, ascii_msg, zh or mapping.zh_msg

    detail_part = _join_details(details)
    base_zh = error_message or mapping.zh_msg
    base_ascii = mapping.ascii_msg
    zh = "|".join(p for p in [base_zh, detail_part] if p)
    # 详情可能含中文，ascii 通道仅附加可打印 ASCII 片段
    ascii_details = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in detail_part).strip()
    ascii_msg = "|".join(p for p in [base_ascii, ascii_details] if p)
    return mapping.platform_code, ascii_msg, zh


def resolve_http_status_auth(status_code: int) -> Optional[Tuple[str, str, str]]:
    if status_code == 401:
        m = BUSINESS_CODE_MAP["AUTH_REQUIRED"]
        return m.platform_code, m.ascii_msg, m.zh_msg
    if status_code == 403:
        m = BUSINESS_CODE_MAP["PERMISSION_DENIED"]
        return m.platform_code, m.ascii_msg, m.zh_msg
    return None


def is_success_body(body: Mapping[str, Any]) -> bool:
    """识别现有业务结果是否成功；不允许仅凭 HTTP 200。"""
    if not isinstance(body, dict):
        return False
    if "error" in body and body.get("error"):
        return False
    code = body.get("code")
    if code is None:
        return False
    try:
        return int(code) == 200
    except (TypeError, ValueError):
        return False


def resolve_from_response_body(
    body: Optional[Mapping[str, Any]],
    http_status: int,
) -> Tuple[str, str, str]:
    """
    从响应 Body + HTTP 状态推导平台业务码。
    返回 (platform_code, ascii_msg, zh_msg)
    """
    auth = resolve_http_status_auth(http_status)
    if auth and (not body or not is_success_body(body)):
        # 401/403 优先按认证失败
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            err = body["error"]
            return resolve_from_error_code(
                err.get("error_code"),
                err.get("error_message"),
                err.get("details"),
            )
        return auth

    if not isinstance(body, dict):
        if 200 <= http_status < 300:
            # 非 JSON 成功响应（极少出现在纳入范围内）
            m = BUSINESS_CODE_MAP["SUCCESS"]
            return m.platform_code, m.ascii_msg, m.zh_msg
        m = BUSINESS_CODE_MAP["UNKNOWN_EXCEPTION"]
        return m.platform_code, m.ascii_msg, m.zh_msg

    if is_success_body(body):
        m = BUSINESS_CODE_MAP["SUCCESS"]
        msg = body.get("message") or m.zh_msg
        ascii_msg = m.ascii_msg if msg in (None, "success", m.zh_msg) else m.ascii_msg
        return m.platform_code, ascii_msg, str(msg)

    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    error_code = err.get("error_code") if err else None
    error_message = err.get("error_message") if err else body.get("message")
    details = err.get("details") if err else None

    if not error_code:
        # HTTP 200 但业务 code 非 200，且无 error 结构
        return resolve_from_error_code(
            "UNKNOWN_BUSINESS_FAILURE",
            error_message or f"Business code={body.get('code')}",
            details,
        )

    # 按 error_code 映射；认证类 HTTP 状态覆盖
    platform_code, ascii_msg, zh_msg = resolve_from_error_code(
        error_code, error_message, details
    )
    if http_status in (401, 403) and not platform_code.startswith("PA-"):
        auth_mapped = resolve_http_status_auth(http_status)
        if auth_mapped:
            return auth_mapped
    return platform_code, ascii_msg, zh_msg

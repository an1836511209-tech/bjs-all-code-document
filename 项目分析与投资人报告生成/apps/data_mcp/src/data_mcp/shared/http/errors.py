from __future__ import annotations

import logging
import re
from typing import NoReturn

import httpx

logger = logging.getLogger(__name__)

_CONFIG_PATH_RE = re.compile(r"(?:data-mcp|config)\.ya?ml[^\s]*", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")
_TOKEN_RE = re.compile(r"(token|api[_-]?key|password|secret)[\"']?\s*[:=]\s*\S+", re.IGNORECASE)


class ExternalServiceError(RuntimeError):
    """外部服务错误：对外仅暴露 public_message，detail 只写日志。"""

    def __init__(self, service: str, public_message: str, *, detail: str = "") -> None:
        self.service = service
        self.public_message = public_message
        self.detail = detail
        super().__init__(public_message)


def sanitize_text(text: str) -> str:
    """移除路径、URL、疑似密钥片段等敏感信息。"""
    cleaned = str(text or "")
    cleaned = _CONFIG_PATH_RE.sub("<config>", cleaned)
    cleaned = _URL_RE.sub("<url>", cleaned)
    cleaned = _TOKEN_RE.sub("<redacted>", cleaned)
    return cleaned.strip()


def public_message_for_exception(exc: BaseException) -> str:
    """将任意异常转为可安全返回给上游的简短说明。"""
    if isinstance(exc, ExternalServiceError):
        return exc.public_message
    if isinstance(exc, ValueError):
        message = str(exc)
        # 保留上市公司画像等可操作说明；其它配置缺失仍泛化
        actionable = ("listed_peer_match", "上市公司画像", "data_dir")
        mentions_config = "配置" in message or "config.yaml" in message.lower()
        if mentions_config and not any(m in message for m in actionable):
            return "配置无效或不完整"
        return sanitize_text(message)
    if isinstance(exc, FileNotFoundError):
        message = sanitize_text(str(exc) or "")
        return message or "未找到所需数据文件"
    if isinstance(exc, httpx.TimeoutException):
        return "外部服务请求超时"
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return _http_status_public("外部服务", exc.response.status_code)
    if isinstance(exc, httpx.HTTPError):
        return "外部服务网络连接失败"
    return "内部服务错误"


def _http_status_public(service: str, status_code: int) -> str:
    if status_code == 429:
        return f"{service} 请求过于频繁，请稍后重试"
    if status_code >= 500:
        return f"{service} 暂时不可用（HTTP {status_code}）"
    return f"{service} 请求被拒绝（HTTP {status_code}）"


def raise_from_http_error(service: str, exc: BaseException) -> NoReturn:
    detail = str(exc)
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        status = exc.response.status_code
        body = exc.response.text[:2000] if exc.response.text else ""
        logger.warning("%s HTTP %s: %s", service, status, body)
        raise ExternalServiceError(
            service,
            _http_status_public(service, status),
            detail=detail,
        ) from exc
    if isinstance(exc, httpx.TimeoutException):
        logger.warning("%s timeout: %s", service, detail)
        raise ExternalServiceError(service, f"{service} 请求超时", detail=detail) from exc
    if isinstance(exc, httpx.HTTPError):
        logger.warning("%s network error: %s", service, detail)
        raise ExternalServiceError(service, f"{service} 网络连接失败", detail=detail) from exc
    logger.exception("%s call failed", service)
    raise ExternalServiceError(service, f"{service} 调用失败", detail=detail) from exc


def raise_invalid_json_response(
    service: str,
    *,
    status_code: int | None = None,
    body: str | None = None,
) -> NoReturn:
    if body:
        logger.warning(
            "%s invalid JSON (status=%s): %s",
            service,
            status_code,
            body[:2000],
        )
    else:
        logger.warning("%s invalid JSON (status=%s)", service, status_code)
    raise ExternalServiceError(service, f"{service} 返回格式无效")

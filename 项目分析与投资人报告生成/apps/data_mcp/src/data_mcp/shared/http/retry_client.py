from __future__ import annotations

import logging
import random
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE_SECONDS = 0.5
DEFAULT_BACKOFF_MAX_SECONDS = 8.0


def is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def is_retryable_http_error(exc: BaseException) -> bool:
    """仅对超时、连接失败、429 与 5xx 返回 True；参数/4xx 业务错误不重试。"""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.NetworkError) and not isinstance(exc, httpx.HTTPStatusError):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return is_retryable_status(exc.response.status_code)
    return False


def _sleep_backoff(attempt: int, *, base: float, maximum: float) -> None:
    delay = min(maximum, base * (2**attempt))
    delay *= 0.5 + random.random() * 0.5
    time.sleep(delay)


def http_request(
    method: str,
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
    service_name: str = "http",
    **kwargs: Any,
) -> httpx.Response:
    """
    带有限重试的 HTTP 请求。
    只重试超时、连接失败、429 与 5xx；4xx（除 429）与参数错误直接抛出。
    """
    verb = method.upper()
    attempts = max_retries + 1
    last_exc: BaseException | None = None

    for attempt in range(attempts):
        try:
            response = httpx.request(verb, url, **kwargs)
            response.raise_for_status()
            if attempt > 0:
                logger.info(
                    "%s %s succeeded after %d retries",
                    service_name,
                    verb,
                    attempt,
                )
            return response
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code if exc.response is not None else 0
            if not is_retryable_status(status) or attempt >= attempts - 1:
                raise
            logger.warning(
                "%s %s HTTP %s retryable, attempt %d/%d",
                service_name,
                verb,
                status,
                attempt + 1,
                attempts,
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            if not is_retryable_http_error(exc) or attempt >= attempts - 1:
                raise
            logger.warning(
                "%s %s transient error (%s), attempt %d/%d",
                service_name,
                verb,
                type(exc).__name__,
                attempt + 1,
                attempts,
            )

        _sleep_backoff(
            attempt,
            base=backoff_base_seconds,
            maximum=backoff_max_seconds,
        )

    assert last_exc is not None
    raise last_exc

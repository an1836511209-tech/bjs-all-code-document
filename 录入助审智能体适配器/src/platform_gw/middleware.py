"""
平台接入 ASGI 中间件

仅处理 PLATFORM_GW_PREFIX 下、且在显式白名单内的路径。
不伪造平台三个响应头；不改动未纳入接口。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, Optional

from loguru import logger
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config.platform_gw_config import (
    PLATFORM_GW_ENABLED,
    PLATFORM_GW_MAX_PAYLOAD_BYTES,
    PLATFORM_GW_PREFIX,
    PLATFORM_GW_PROVIDER_API_KEY,
)
from src.platform_gw.adapter import adapt_json_response, merge_headers
from src.platform_gw.constants import (
    HEADER_GW_BIZ_CODE,
    HEADER_GW_BIZ_MSG,
    HEADER_PROVIDER_API_KEY,
    PLATFORM_GENERATED_HEADERS,
)
from src.platform_gw.header_codec import encode_biz_msg
from src.platform_gw.mapping import BUSINESS_CODE_MAP
from src.platform_gw.scope import is_included_path, is_platform_prefix, is_special_non_json_response


class PlatformGwMiddleware:
    def __init__(self, app: ASGIApp, enabled: bool | None = None, prefix: str | None = None):
        self.app = app
        self.enabled = PLATFORM_GW_ENABLED if enabled is None else enabled
        self.prefix = (prefix or PLATFORM_GW_PREFIX).rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if not is_platform_prefix(path, self.prefix):
            await self.app(scope, receive, send)
            return

        # 提供方可选鉴权（不信任 x-gw-*）
        auth_response = self._check_provider_auth(scope)
        if auth_response is not None:
            await auth_response(scope, receive, send)
            return

        if not is_included_path(path, self.prefix):
            # 前缀下但未纳入：原样转发，不补业务头
            await self.app(scope, receive, send)
            return

        await self._adapt_included(scope, receive, send)

    def _check_provider_auth(self, scope: Scope) -> Optional[ASGIApp]:
        expected = PLATFORM_GW_PROVIDER_API_KEY
        if not expected:
            return None

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        provided = headers.get(HEADER_PROVIDER_API_KEY.lower())
        if not provided:
            mapping = BUSINESS_CODE_MAP["AUTH_REQUIRED"]
            return self._auth_failure_app(401, mapping)
        if provided != expected:
            # 不记录密钥内容
            logger.warning("platform_gw provider api key mismatch")
            mapping = BUSINESS_CODE_MAP["AUTH_INVALID"]
            return self._auth_failure_app(401, mapping)
        return None

    def _auth_failure_app(self, status_code: int, mapping) -> ASGIApp:
        header_msg, _ = encode_biz_msg(mapping.ascii_msg, mapping.zh_msg)
        if mapping.platform_code == "PA-002":
            error_code = "AUTH_INVALID"
        elif mapping.platform_code.startswith("PA-"):
            error_code = "AUTH_REQUIRED"
        else:
            error_code = "PERMISSION_DENIED"
        body = {
            "code": status_code,
            "message": "Unauthorized",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "error": {
                "error_code": error_code,
                "error_message": mapping.zh_msg,
                "details": None,
            },
        }

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            response = JSONResponse(
                status_code=status_code,
                content=body,
                headers={
                    HEADER_GW_BIZ_CODE: mapping.platform_code,
                    HEADER_GW_BIZ_MSG: header_msg,
                },
            )
            await response(scope, receive, send)

        return app

    @staticmethod
    def _encode_header_pair(key: str, value: str) -> tuple[bytes, bytes]:
        """ASGI 头值需 latin-1；非 latin-1 时回退为 ASCII 安全替换。"""
        try:
            return key.encode("latin-1"), value.encode("latin-1")
        except UnicodeEncodeError:
            safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in value)
            return key.encode("latin-1"), safe.encode("latin-1")

    async def _adapt_included(self, scope: Scope, receive: Receive, send: Send) -> None:
        body_chunks: list[bytes] = []
        status_code_box: dict = {"code": 200}
        response_headers: list[tuple[bytes, bytes]] = []
        started = {"done": False}
        streaming = {"value": False}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code_box["code"] = message["status"]
                response_headers.clear()
                response_headers.extend(message.get("headers") or [])
                # 延后发送，等 body 收齐（非流式）
                return

            if message["type"] == "http.response.body":
                body = message.get("body", b"") or b""
                more = message.get("more_body", False)

                # 检测是否流式：若 start 时 content-type 已是特殊类型，或分块持续
                header_dict = {
                    k.decode("latin-1").lower(): v.decode("latin-1")
                    for k, v in response_headers
                }
                content_type = header_dict.get("content-type", "")

                if is_special_non_json_response(content_type):
                    streaming["value"] = True
                    if not started["done"]:
                        # 特殊响应：不缓冲、不改 Body；流式场景限制见接入文档
                        await self._send_start_passthrough(
                            send, status_code_box["code"], response_headers, special=True
                        )
                        started["done"] = True
                    await send(message)
                    return

                body_chunks.append(body)
                if more:
                    # 继续缓冲；若过大则提前截断缓冲（仍不发送半截业务 JSON）
                    if sum(len(c) for c in body_chunks) > PLATFORM_GW_MAX_PAYLOAD_BYTES * 2:
                        body_chunks[:] = [
                            b"".join(body_chunks)[: PLATFORM_GW_MAX_PAYLOAD_BYTES + 1]
                        ]
                    return

                full_body = b"".join(body_chunks)
                new_body, new_status, header_updates = adapt_json_response(
                    full_body,
                    status_code_box["code"],
                    {},
                    max_bytes=PLATFORM_GW_MAX_PAYLOAD_BYTES,
                )

                final_headers = MutableHeaders(raw=list(response_headers))
                if "content-length" in final_headers:
                    del final_headers["content-length"]
                merge_headers(final_headers, header_updates)
                for name in list(final_headers.keys()):
                    if name.lower() in {h.lower() for h in PLATFORM_GENERATED_HEADERS}:
                        del final_headers[name]

                await send(
                    {
                        "type": "http.response.start",
                        "status": new_status,
                        "headers": [
                            self._encode_header_pair(k, v)
                            for k, v in final_headers.items()
                        ],
                    }
                )
                started["done"] = True
                await send(
                    {
                        "type": "http.response.body",
                        "body": new_body,
                        "more_body": False,
                    }
                )
                return

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            # FastAPI/Starlette 将未捕获 Exception 交由最外层 ServerErrorMiddleware
            # 处理，会绕过本中间件的 send_wrapper。这里在响应尚未发出时拦截，
            # 补齐 PI 类业务头；不吞掉已开始的响应，也不改变事务回滚语义。
            if started["done"] or streaming["value"]:
                raise
            logger.error(f"platform_gw unhandled exception: {exc}", exc_info=True)
            mapping = BUSINESS_CODE_MAP["INTERNAL_ERROR"]
            header_msg, _ = encode_biz_msg(mapping.ascii_msg, mapping.zh_msg)
            body = {
                "code": 500,
                "message": "Internal Server Error",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "error": {
                    "error_code": "INTERNAL_ERROR",
                    "error_message": mapping.zh_msg,
                    "details": None,
                },
            }
            response = JSONResponse(
                status_code=500,
                content=body,
                headers={
                    HEADER_GW_BIZ_CODE: mapping.platform_code,
                    HEADER_GW_BIZ_MSG: header_msg,
                },
            )
            await response(scope, receive, send)

    async def _send_start_passthrough(
        self,
        send: Send,
        status: int,
        response_headers: list,
        *,
        special: bool,
    ) -> None:
        headers = MutableHeaders(raw=list(response_headers))
        for name in list(headers.keys()):
            if name.lower() in {h.lower() for h in PLATFORM_GENERATED_HEADERS}:
                del headers[name]
        # 特殊流式/文件：不根据 Body 判成功；2xx 时若无业务头则不强制写 PS-001，
        # 避免在流式中途失败时无法回滚头。文档中列为限制。
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    self._encode_header_pair(k, v) for k, v in headers.items()
                ],
            }
        )

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from data_mcp.mcp.errors import McpClientError, McpErrorCode
from data_mcp.mcp.schemas import validate_tool_input, validate_tool_output
from data_mcp.shared.http.errors import public_message_for_exception

logger = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_CALL_TIMEOUT_SECONDS = 180.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 1


def _default_server_params(
    *,
    command: str | None = None,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> StdioServerParameters:
    child_env = dict(os.environ)
    if env:
        child_env.update(env)
    return StdioServerParameters(
        command=command or sys.executable,
        args=args or ["-m", "data_mcp", "--transport", "stdio"],
        cwd=str(cwd or APP_ROOT),
        env=child_env,
    )


def _extract_tool_payload(result: Any) -> Any:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured

    content = getattr(result, "content", None) or []
    texts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            texts.append(text)
    if not texts:
        raise McpClientError(
            McpErrorCode.PROTOCOL,
            "工具返回无 structured_content 或 text content",
        )
    joined = "\n".join(texts).strip()
    try:
        return json.loads(joined)
    except json.JSONDecodeError as exc:
        logger.warning("MCP tool response is not valid JSON: %s", joined[:500])
        raise McpClientError(
            McpErrorCode.PROTOCOL,
            "工具返回不是合法 JSON",
        ) from exc


def _is_retryable_client_error(exc: BaseException) -> bool:
    if isinstance(exc, McpClientError):
        return exc.code in {McpErrorCode.TIMEOUT, McpErrorCode.CONNECTION, McpErrorCode.PROTOCOL}
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return True
    return False


@asynccontextmanager
async def open_mcp_session(
    *,
    command: str | None = None,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
) -> AsyncIterator[ClientSession]:
    params = _default_server_params(command=command, args=args, cwd=cwd, env=env)
    started = time.perf_counter()
    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=connect_timeout_seconds)
                logger.info(
                    "MCP session initialized in %.2fs (cwd=%s)",
                    time.perf_counter() - started,
                    params.cwd,
                )
                yield session
    except TimeoutError as exc:
        raise McpClientError(
            McpErrorCode.TIMEOUT,
            f"连接 MCP 服务超时（>{connect_timeout_seconds}s）",
        ) from exc
    except Exception as exc:
        if isinstance(exc, McpClientError):
            raise
        logger.warning("MCP session connection failed: %s", exc)
        raise McpClientError(
            McpErrorCode.CONNECTION,
            "连接 MCP 服务失败",
        ) from exc


class DataMcpClient:
    """项目内 MCP stdio 客户端：统一超时、重试、错误码与调用日志。"""

    def __init__(
        self,
        *,
        command: str | None = None,
        args: list[str] | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        call_timeout_seconds: float = DEFAULT_CALL_TIMEOUT_SECONDS,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        validate_io: bool = True,
    ) -> None:
        self.command = command
        self.args = args
        self.cwd = cwd
        self.env = env
        self.call_timeout_seconds = call_timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self.max_retries = max_retries
        self.validate_io = validate_io

    async def list_tools(self) -> list[str]:
        async with open_mcp_session(
            command=self.command,
            args=self.args,
            cwd=self.cwd,
            env=self.env,
            connect_timeout_seconds=self.connect_timeout_seconds,
        ) as session:
            result = await session.list_tools()
            return sorted(tool.name for tool in result.tools)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(arguments or {})
        if self.validate_io:
            try:
                validate_tool_input(name, payload)
            except ValueError as exc:
                raise McpClientError(
                    McpErrorCode.VALIDATION,
                    str(exc),
                    tool=name,
                ) from exc

        attempts = self.max_retries + 1
        last_exc: BaseException | None = None

        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                async with open_mcp_session(
                    command=self.command,
                    args=self.args,
                    cwd=self.cwd,
                    env=self.env,
                    connect_timeout_seconds=self.connect_timeout_seconds,
                ) as session:
                    result = await asyncio.wait_for(
                        session.call_tool(name, payload),
                        timeout=self.call_timeout_seconds,
                    )
            except TimeoutError as exc:
                last_exc = McpClientError(
                    McpErrorCode.TIMEOUT,
                    f"调用工具超时（>{self.call_timeout_seconds}s）",
                    tool=name,
                )
                if attempt >= attempts - 1:
                    raise last_exc from exc
                logger.warning(
                    "MCP tool %s timeout, retry %d/%d",
                    name,
                    attempt + 1,
                    attempts,
                )
                continue
            except McpClientError as exc:
                last_exc = exc
                if not _is_retryable_client_error(exc) or attempt >= attempts - 1:
                    raise
                logger.warning(
                    "MCP tool %s %s, retry %d/%d",
                    name,
                    exc.code,
                    attempt + 1,
                    attempts,
                )
                continue
            except Exception as exc:
                wrapped = McpClientError(
                    McpErrorCode.UNKNOWN,
                    public_message_for_exception(exc),
                    tool=name,
                )
                last_exc = wrapped
                if not _is_retryable_client_error(exc) or attempt >= attempts - 1:
                    raise wrapped from exc
                logger.warning(
                    "MCP tool %s unknown error, retry %d/%d: %s",
                    name,
                    attempt + 1,
                    attempts,
                    exc,
                )
                continue

            elapsed = time.perf_counter() - started
            if getattr(result, "is_error", False):
                detail = _extract_tool_payload(result)
                if isinstance(detail, str):
                    message = public_message_for_exception(Exception(detail))
                else:
                    message = "工具执行失败"
                raise McpClientError(
                    McpErrorCode.TOOL_ERROR,
                    message,
                    tool=name,
                )

            data = _extract_tool_payload(result)
            if not isinstance(data, dict):
                raise McpClientError(
                    McpErrorCode.PROTOCOL,
                    f"工具返回须为 JSON 对象，收到: {type(data).__name__}",
                    tool=name,
                )

            if self.validate_io:
                validate_tool_output(name, data)

            logger.info(
                "MCP tool %s ok in %.2fs (attempt=%d)",
                name,
                elapsed,
                attempt + 1,
            )
            return data

        assert last_exc is not None
        raise last_exc

    def call_tool_sync(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return asyncio.run(self.call_tool(name, arguments))

    def list_tools_sync(self) -> list[str]:
        return asyncio.run(self.list_tools())

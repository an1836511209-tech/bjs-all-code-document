from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from data_mcp.mcp.responses import failed_envelope
from data_mcp.mcp.schemas import validate_tool_output
from data_mcp.shared.http.errors import ExternalServiceError, public_message_for_exception

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class McpToolError(RuntimeError):
    """MCP 工具边界错误：消息可安全返回给客户端。"""

    def __init__(self, tool: str, message: str, *, code: str = "TOOL_ERROR") -> None:
        self.tool = tool
        self.code = code
        self.message = message
        super().__init__(message)


def to_mcp_tool_error(tool: str, exc: BaseException) -> McpToolError:
    if isinstance(exc, McpToolError):
        return exc
    # ValueError / FileNotFoundError：消息对 agent 可读，按校验类错误返回
    if isinstance(exc, (ValueError, FileNotFoundError)):
        return McpToolError(
            tool,
            public_message_for_exception(exc),
            code="VALIDATION",
        )
    if isinstance(exc, ExternalServiceError):
        return McpToolError(tool, exc.public_message, code="UPSTREAM")
    logger.exception("MCP tool %s failed", tool, exc_info=exc)
    return McpToolError(tool, "工具执行失败", code="INTERNAL")


def guard_tool_errors(tool_name: str) -> Callable[[F], F]:
    """包装 MCP 工具：技术细节写日志，向 Agent 返回失败外壳和空数据。"""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                error = to_mcp_tool_error(tool_name, exc)
                if error.code == "VALIDATION":
                    message = error.message
                elif error.code == "UPSTREAM":
                    message = "数据源暂不可用，本次未获取到合适数据"
                else:
                    message = "工具暂不可用，本次未获取到合适数据"
                logger.exception("MCP tool %s failed", tool_name, exc_info=exc)
                result = failed_envelope(tool_name, message=message, code=error.code)
                validate_tool_output(tool_name, result)
                return result

        return wrapper  # type: ignore[return-value]

    return decorator

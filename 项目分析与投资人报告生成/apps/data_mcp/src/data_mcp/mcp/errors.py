from __future__ import annotations

from enum import StrEnum
from typing import Any


class McpErrorCode(StrEnum):
    TIMEOUT = "MCP_TIMEOUT"
    CONNECTION = "MCP_CONNECTION"
    PROTOCOL = "MCP_PROTOCOL"
    TOOL_ERROR = "MCP_TOOL_ERROR"
    VALIDATION = "MCP_VALIDATION"
    UNKNOWN = "MCP_UNKNOWN"


class McpClientError(Exception):
    """MCP 客户端统一异常，含稳定错误码供下游处理。"""

    def __init__(
        self,
        code: McpErrorCode,
        message: str,
        *,
        tool: str = "",
        details: Any = None,
    ) -> None:
        self.code = code
        self.tool = tool
        self.details = details
        prefix = f"[{code}]"
        if tool:
            prefix = f"[{code}:{tool}]"
        super().__init__(f"{prefix} {message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": str(self.code),
            "message": str(self),
            "tool": self.tool or None,
            "details": self.details,
        }

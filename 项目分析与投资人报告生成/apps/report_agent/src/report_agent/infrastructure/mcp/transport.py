"""Narrow transport protocol owned by Report Agent."""

from __future__ import annotations

from typing import Any, Protocol


class McpTransport(Protocol):
    async def list_tools(self) -> tuple[str, ...]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...

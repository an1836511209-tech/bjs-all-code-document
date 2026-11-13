"""Official MCP SDK Streamable HTTP transport adapter."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class McpTransportError(RuntimeError):
    """Raised when the MCP transport or response envelope is invalid."""


class StreamableHttpMcpTransport:
    def __init__(self, url: str, *, timeout_seconds: int = 600) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MCP URL must be an absolute HTTP(S) endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("MCP URL cannot contain credentials, query, or fragment")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        self._url = url
        self._timeout_seconds = timeout_seconds

    async def list_tools(self) -> tuple[str, ...]:
        async with streamable_http_client(self._url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=self._timeout_seconds)
                result = await asyncio.wait_for(session.list_tools(), timeout=self._timeout_seconds)
                return tuple(sorted(tool.name for tool in result.tools))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with streamable_http_client(self._url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=self._timeout_seconds)
                result = await asyncio.wait_for(
                    session.call_tool(name, arguments), timeout=self._timeout_seconds
                )
        payload = self._extract_payload(result)
        if getattr(result, "is_error", False):
            raise McpTransportError(f"Data MCP tool reported a protocol error: {name}")
        if not isinstance(payload, dict):
            raise McpTransportError(f"Data MCP tool must return a JSON object: {name}")
        return payload

    @staticmethod
    def _extract_payload(result: Any) -> Any:
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        texts = [
            text
            for block in (getattr(result, "content", None) or [])
            if isinstance((text := getattr(block, "text", None)), str)
        ]
        if not texts:
            raise McpTransportError("Data MCP response has no structured or text content")
        try:
            return json.loads("\n".join(texts))
        except json.JSONDecodeError as exc:
            raise McpTransportError("Data MCP text response is not valid JSON") from exc
